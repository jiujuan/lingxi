"""MinerU HTTP parser: PDF / Office / image documents via a self-hosted
``mineru-api`` (or ``mineru-router``) service.

The exact response envelope of ``POST /file_parse`` drifts across mineru-api
3.x versions (direct JSON result vs task-id + poll). Everything
endpoint-shaped lives in :class:`MinerUClient` and payload interpretation is
funneled through ``_extract_result`` — that method is the single point of
change when the deployed MinerU version changes. Errors are always raised as
:class:`ParserError` so the Celery retry pipeline can act on ``retryable``.
"""

from dataclasses import dataclass, replace
import json
import time

from server.app.core.config import settings
from server.app.integrations.parsers._http import RetryingHttpClient
from server.app.services.chunking.contracts import BlockType
from server.app.integrations.parsers.base import (
    ParsedBlock,
    ParsedDocument,
    ParseRequest,
    ParserAdapter,
    ParserError,
)
from server.app.integrations.parsers.markdown_blocks import (
    markdown_from_blocks,
    split_markdown_blocks,
)

_TASK_SUCCESS_STATES = {"done", "completed", "success", "succeeded", "finished"}
_TASK_FAILURE_STATES = {"failed", "error", "cancelled"}

_MINERU_BLOCK_TYPES = {
    "text": BlockType.TEXT,
    "list": BlockType.LIST,
    "list_item": BlockType.LIST,
    "table": BlockType.TABLE,
    "image": BlockType.IMAGE,
    "equation": BlockType.FORMULA,
    "formula": BlockType.FORMULA,
    "code": BlockType.CODE,
    "quote": BlockType.QUOTE,
    "blockquote": BlockType.QUOTE,
}


def _fallback_blocks(markdown: str, reason: str) -> list[ParsedBlock]:
    return [
        replace(
            block,
            metadata={
                **block.metadata,
                "parserFallback": True,
                "fallbackReason": reason,
            },
        )
        for block in split_markdown_blocks(markdown)
    ]


@dataclass(frozen=True)
class MinerUResult:
    markdown: str | None
    content_list: list[dict] | None


class MinerUClient(RetryingHttpClient):
    service_label = "MinerU"

    def __init__(
        self,
        base_url: str | None,
        api_key: str | None = None,
        *,
        timeout_ms: int = 30000,
        poll_interval_seconds: float = 3.0,
        max_wait_seconds: int = 600,
        backend: str | None = None,
        lang: str | None = None,
        max_retries: int = 2,
    ) -> None:
        super().__init__(
            base_url,
            api_key,
            timeout_ms=timeout_ms,
            poll_interval_seconds=poll_interval_seconds,
            max_wait_seconds=max_wait_seconds,
            max_retries=max_retries,
        )
        self.backend = backend
        self.lang = lang

    @classmethod
    def from_settings(cls) -> "MinerUClient":
        return cls(
            settings.mineru_base_url,
            settings.mineru_api_key,
            timeout_ms=settings.mineru_timeout_ms,
            poll_interval_seconds=settings.mineru_poll_interval_seconds,
            max_wait_seconds=settings.mineru_max_wait_seconds,
            backend=settings.mineru_backend,
            lang=settings.mineru_lang,
        )

    def _headers(self) -> dict[str, str]:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    def parse_file(self, file_name: str, content: bytes, mime_type: str) -> MinerUResult:
        if not self.configured:
            raise ParserError(
                "PARSER_UNAVAILABLE", "MinerU 解析服务未配置", retryable=False
            )
        deadline = time.monotonic() + self.max_wait_seconds
        form: dict[str, str] = {"return_md": "true", "return_content_list": "true"}
        if self.backend:
            form["backend"] = self.backend
        if self.lang:
            form["lang"] = self.lang
        payload = self._request_json(
            "POST",
            f"{self.base_url}/file_parse",
            # Direct mode parses synchronously before responding, so the
            # submit call gets the full parse deadline, not the per-call one.
            timeout_seconds=self.max_wait_seconds,
            data=form,
            files={"files": (file_name, content, mime_type)},
        )

        task_id = self._extract_task_id(payload)
        if task_id is not None:
            payload = self._poll_task(task_id, deadline)
        return self._extract_result(payload)

    # -- Task polling ----------------------------------------------------------

    def _poll_task(self, task_id: str, deadline: float) -> dict:
        while True:
            if time.monotonic() > deadline:
                raise ParserError(
                    "PARSER_TIMEOUT",
                    f"MinerU 解析超过 {self.max_wait_seconds}s 未完成",
                    retryable=True,
                )
            payload = self._request_json(
                "GET",
                f"{self.base_url}/tasks/{task_id}",
                timeout_seconds=self.timeout_seconds,
            )
            state = str(
                payload.get("state") or payload.get("status") or ""
            ).lower()
            if state in _TASK_FAILURE_STATES:
                message = str(
                    payload.get("error")
                    or payload.get("message")
                    or "MinerU 解析任务失败"
                )
                # Deterministic causes (corrupt file) dominate task-level
                # failures; retrying would burn 3 full parse deadlines.
                raise ParserError("PARSER_FAILED", message, retryable=False)
            if state in _TASK_SUCCESS_STATES:
                return self._request_json(
                    "GET",
                    f"{self.base_url}/tasks/{task_id}/result",
                    timeout_seconds=self.timeout_seconds,
                )
            time.sleep(self.poll_interval_seconds)

    # -- Payload interpretation (single point of change) ------------------------

    @staticmethod
    def _extract_task_id(payload: dict) -> str | None:
        for key in ("task_id", "taskId"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("task_id", "taskId"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return value
        return None

    @classmethod
    def _extract_result(cls, payload: dict) -> MinerUResult:
        """Normalise the parse payload across mineru-api envelope variants:
        flat fields, ``{"data": {...}}``, or per-file ``{"results": {...}}``."""
        node = payload
        if isinstance(node.get("data"), dict):
            node = node["data"]
        results = node.get("results")
        if isinstance(results, dict) and results:
            node = next(iter(results.values()))
            if not isinstance(node, dict):
                raise ParserError(
                    "PARSER_RESPONSE_INVALID", "MinerU 返回了非预期的结果结构"
                )

        markdown: str | None = None
        for key in ("md_content", "markdown", "md"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                markdown = value
                break

        content_list = node.get("content_list")
        if isinstance(content_list, str):
            try:
                content_list = json.loads(content_list)
            except (ValueError, json.JSONDecodeError):
                content_list = None
        if not isinstance(content_list, list):
            content_list = None
        else:
            content_list = [item for item in content_list if isinstance(item, dict)]

        if markdown is None and not content_list:
            raise ParserError(
                "PARSER_RESPONSE_INVALID",
                "MinerU 响应中缺少 markdown 与 content_list",
            )
        return MinerUResult(markdown=markdown, content_list=content_list or None)


class MinerUParser(ParserAdapter):
    name = "MINERU"
    version = "1.0"
    extensions = frozenset(
        {".pdf", ".docx", ".pptx", ".xlsx", ".png", ".jpg", ".jpeg"}
    )
    mime_types = frozenset(
        {
            "application/pdf",
            "image/png",
            "image/jpeg",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
    )

    def __init__(self, client: MinerUClient | None = None) -> None:
        self._client = client or MinerUClient.from_settings()

    def is_available(self) -> bool:
        return self._client.configured

    def parse(self, request: ParseRequest) -> ParsedDocument:
        source = request.source
        if not self.supports(source):
            raise ParserError("UNSUPPORTED_FILE_TYPE", "MinerU 解析器不支持该文件类型")

        result = self._client.parse_file(
            source.file_name, source.content, source.mime_type
        )
        warnings: list[str] = []

        if result.content_list:
            blocks, page_count, block_warnings = self._blocks_from_content_list(
                result.content_list
            )
            warnings.extend(block_warnings)
            markdown = result.markdown
            if markdown is None:
                markdown = markdown_from_blocks(blocks)
                warnings.append("MinerU 未返回 markdown，已由结构化内容合成")
            if not blocks and markdown:
                # Structured content_list yielded nothing usable (e.g. only
                # headings/uncaptioned images, or a schema this builder doesn't
                # recognise) but markdown is present — split that so the
                # document isn't lost to a downstream "no chunk" error.
                blocks = _fallback_blocks(markdown, "MINERU_STRUCTURED_CONTENT_EMPTY")
                page_count = page_count or (1 if markdown else 0)
                warnings.append("MinerU 结构化内容为空，已按 markdown 回退切分")
        else:
            markdown = result.markdown or ""
            blocks = _fallback_blocks(markdown, "MINERU_CONTENT_LIST_MISSING")
            page_count = 1 if markdown else 0
            warnings.append("MinerU 未返回 content_list，已按 markdown 回退切分")

        return ParsedDocument(
            parser_name=self.name,
            parser_version=self.version,
            markdown=markdown,
            blocks=blocks,
            page_count=page_count,
            warnings=warnings,
        )

    @staticmethod
    def _blocks_from_content_list(
        items: list[dict],
    ) -> tuple[list[ParsedBlock], int | None, list[str]]:
        blocks: list[ParsedBlock] = []
        title_path: list[str] = []
        page_count: int | None = None
        skipped_images = 0

        for item_index, item in enumerate(items):
            item_type = str(item.get("type") or "text")
            page_idx = item.get("page_idx")
            page_no = page_idx + 1 if isinstance(page_idx, int) and page_idx >= 0 else None
            if page_no is not None:
                page_count = max(page_count or 0, page_no)

            text = str(item.get("text") or "").strip()
            level = item.get("text_level")
            if item_type == "text" and isinstance(level, int) and level >= 1 and text:
                # Headings shape the breadcrumb and are not emitted as blocks,
                # mirroring the markdown splitter's behavior.
                title_path = title_path[: max(level - 1, 0)] + [text]
                continue

            if item_type == "image":
                captions = item.get("image_caption") or item.get("img_caption") or []
                if isinstance(captions, str):
                    captions = [captions]
                caption = " ".join(
                    part.strip() for part in captions if str(part).strip()
                )
                if not caption:
                    skipped_images += 1
                    continue
                content = f"[图片] {caption}"
            elif item_type == "table":
                captions = item.get("table_caption") or []
                if isinstance(captions, str):
                    captions = [captions]
                body = str(item.get("table_body") or "").strip()
                parts = [str(part).strip() for part in captions if str(part).strip()]
                if body:
                    parts.append(body)
                content = "\n".join(parts)
            else:
                # text / equation (LaTeX in ``text``) / unknown types with text
                content = text
            if not content:
                continue

            raw_bbox = item.get("bbox")
            metadata = {
                "sourceLabel": item_type,
                "pageNo": page_no,
                "blockIndex": item_index,
            }
            if raw_bbox is not None:
                metadata["bbox"] = raw_bbox
            if item.get("self_ref") is not None:
                metadata["selfRef"] = item.get("self_ref")
            blocks.append(
                ParsedBlock(
                    index=len(blocks),
                    content=content,
                    page_no=page_no,
                    title_path=list(title_path),
                    source_locator={"pageNo": page_no, "blockIndex": item_index},
                    block_type=_MINERU_BLOCK_TYPES.get(item_type, BlockType.UNKNOWN),
                    structural_id=f"mineru:block:{item_index}",
                    parent_structural_id=(
                        f"mineru:section:{'/'.join(title_path)}" if title_path else None
                    ),
                    metadata=metadata,
                )
            )

        warnings: list[str] = []
        if skipped_images:
            warnings.append(
                "IMAGE_WITHOUT_TEXT_SKIPPED: MinerU skipped "
                f"{skipped_images} image blocks without caption"
            )
        return blocks, page_count, warnings
