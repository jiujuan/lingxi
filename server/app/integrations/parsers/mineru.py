"""MinerU HTTP parser: PDF / Office / image documents via a self-hosted
``mineru-api`` (or ``mineru-router``) service.

The exact response envelope of ``POST /file_parse`` drifts across mineru-api
3.x versions (direct JSON result vs task-id + poll). Everything
endpoint-shaped lives in :class:`MinerUClient` and payload interpretation is
funneled through ``_extract_result`` — that method is the single point of
change when the deployed MinerU version changes. Errors are always raised as
:class:`ParserError` so the Celery retry pipeline can act on ``retryable``.
"""

from dataclasses import dataclass
import json
import time

import httpx

from server.app.core.config import settings
from server.app.integrations.parsers.base import (
    ParsedBlock,
    ParsedDocument,
    ParseRequest,
    ParserAdapter,
    ParserError,
)
from server.app.integrations.parsers.markdown_blocks import split_markdown_blocks

_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
_TASK_SUCCESS_STATES = {"done", "completed", "success", "succeeded", "finished"}
_TASK_FAILURE_STATES = {"failed", "error", "cancelled"}


@dataclass(frozen=True)
class MinerUResult:
    markdown: str | None
    content_list: list[dict] | None


class MinerUClient:
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
        self.base_url = (base_url or "").rstrip("/") or None
        self.api_key = api_key
        self.timeout_seconds = max(1.0, timeout_ms / 1000)
        self.poll_interval_seconds = max(0.1, poll_interval_seconds)
        self.max_wait_seconds = max(1, max_wait_seconds)
        self.backend = backend
        self.lang = lang
        self.max_retries = max(0, max_retries)

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

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

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

    # -- HTTP plumbing ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        timeout_seconds: float,
        data: dict | None = None,
        files: dict | None = None,
    ) -> dict:
        last_error: ParserError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=timeout_seconds) as client:
                    response = client.request(
                        method, url, headers=self._headers(), data=data, files=files
                    )
                if response.status_code in _RETRYABLE_STATUS:
                    last_error = ParserError(
                        "PARSER_UNAVAILABLE",
                        f"MinerU 服务返回 HTTP {response.status_code}",
                        retryable=True,
                    )
                    if attempt < self.max_retries:
                        self._sleep_backoff(attempt)
                        continue
                    raise last_error
                if response.status_code >= 400:
                    raise ParserError(
                        "PARSER_REQUEST_ERROR",
                        f"MinerU 服务拒绝请求 HTTP {response.status_code}",
                        retryable=False,
                    )
                try:
                    payload = response.json()
                except (ValueError, json.JSONDecodeError) as exc:
                    raise ParserError(
                        "PARSER_RESPONSE_INVALID", "MinerU 返回非 JSON 响应"
                    ) from exc
                if not isinstance(payload, dict):
                    raise ParserError(
                        "PARSER_RESPONSE_INVALID", "MinerU 返回了非预期的响应结构"
                    )
                return payload
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = ParserError(
                    "PARSER_UNAVAILABLE",
                    f"MinerU 服务连接失败：{exc}",
                    retryable=True,
                )
                if attempt < self.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise last_error from exc
        raise last_error or ParserError(
            "PARSER_UNAVAILABLE", "MinerU 服务不可用", retryable=True
        )

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        time.sleep(min(8.0, 0.5 * (2**attempt)))

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
                markdown = self._markdown_from_blocks(blocks)
                warnings.append("MinerU 未返回 markdown，已由结构化内容合成")
        else:
            markdown = result.markdown or ""
            blocks = split_markdown_blocks(markdown)
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

            blocks.append(
                ParsedBlock(
                    index=len(blocks),
                    content=content,
                    page_no=page_no,
                    title_path=list(title_path),
                    source_locator={"pageNo": page_no, "blockIndex": item_index},
                )
            )

        warnings: list[str] = []
        if skipped_images:
            warnings.append(f"跳过 {skipped_images} 张无描述图片")
        return blocks, page_count, warnings

    @staticmethod
    def _markdown_from_blocks(blocks: list[ParsedBlock]) -> str:
        lines: list[str] = []
        emitted_path: list[str] = []
        for block in blocks:
            if block.title_path != emitted_path:
                for depth, title in enumerate(block.title_path, start=1):
                    if depth > len(emitted_path) or emitted_path[depth - 1] != title:
                        lines.append("#" * depth + " " + title)
                emitted_path = list(block.title_path)
            lines.append(block.content)
            lines.append("")
        return "\n".join(lines).strip()
