"""Docling HTTP parser via a self-hosted ``docling-serve`` (stable v1 API).

Always uses the async endpoints (``POST /v1/convert/file/async`` →
``GET /v1/status/poll/{id}`` → ``GET /v1/result/{id}``): the sync endpoint
enforces a ~2-minute server-side timeout that large documents exceed. Payload
interpretation is funneled through ``_extract_task_id``/``_extract_result`` —
the single point of change when docling-serve's envelope drifts across
versions. Errors carry the same ``ParserError`` code matrix as MinerU so the
Celery retry pipeline treats both engines identically.
"""

from dataclasses import dataclass
import time

from server.app.core.config import settings
from server.app.integrations.parsers._http import RetryingHttpClient
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

_TASK_SUCCESS_STATES = {"success"}
_TASK_FAILURE_STATES = {"failure", "cancelled", "canceled"}
# Body items that never become retrievable blocks: page furniture, and
# standalone captions (captions are attached via their owner's refs).
_SKIP_LABELS = {"page_header", "page_footer", "footnote", "caption"}


@dataclass(frozen=True)
class DoclingResult:
    markdown: str | None
    docling_document: dict | None


class DoclingClient(RetryingHttpClient):
    service_label = "Docling"

    def __init__(
        self,
        base_url: str | None,
        api_key: str | None = None,
        *,
        timeout_ms: int = 30000,
        poll_interval_seconds: float = 3.0,
        max_wait_seconds: int = 600,
        do_ocr: str | None = None,
        ocr_lang: str | None = None,
        pdf_backend: str | None = None,
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
        self.do_ocr = do_ocr
        self.ocr_lang = ocr_lang
        self.pdf_backend = pdf_backend

    @classmethod
    def from_settings(cls) -> "DoclingClient":
        return cls(
            settings.docling_base_url,
            settings.docling_api_key,
            timeout_ms=settings.docling_timeout_ms,
            poll_interval_seconds=settings.docling_poll_interval_seconds,
            max_wait_seconds=settings.docling_max_wait_seconds,
            do_ocr=settings.docling_do_ocr,
            ocr_lang=settings.docling_ocr_lang,
            pdf_backend=settings.docling_pdf_backend,
        )

    def _headers(self) -> dict[str, str]:
        if self.api_key:
            return {"X-Api-Key": self.api_key}
        return {}

    def parse_file(self, file_name: str, content: bytes, mime_type: str) -> DoclingResult:
        if not self.configured:
            raise ParserError(
                "PARSER_UNAVAILABLE", "Docling 解析服务未配置", retryable=False
            )
        deadline = time.monotonic() + self.max_wait_seconds
        form: dict = {
            "to_formats": ["md", "json"],
            # "embedded" (the server default) base64-inlines every image into
            # md_content and bloats the stored ParseArtifact.
            "image_export_mode": "placeholder",
        }
        if self.do_ocr:
            form["do_ocr"] = self.do_ocr
        if self.ocr_lang:
            form["ocr_lang"] = self.ocr_lang
        if self.pdf_backend:
            form["pdf_backend"] = self.pdf_backend
        # Unlike MinerU's direct mode, the async submit returns immediately,
        # so the per-call timeout is sufficient here.
        payload = self._request_json(
            "POST",
            f"{self.base_url}/v1/convert/file/async",
            timeout_seconds=self.timeout_seconds,
            data=form,
            files={"files": (file_name, content, mime_type)},
        )
        task_id = self._extract_task_id(payload)
        if task_id is None:
            raise ParserError(
                "PARSER_RESPONSE_INVALID", "Docling 提交响应缺少 task_id"
            )
        # A tiny document may already be terminal in the submit response.
        return self._extract_result(
            self._poll_task(task_id, deadline, initial_state=self._task_state(payload))
        )

    # -- Task polling ----------------------------------------------------------

    def _poll_task(self, task_id: str, deadline: float, initial_state: str = "") -> dict:
        state = initial_state
        while True:
            if state in _TASK_FAILURE_STATES:
                raise ParserError(
                    "PARSER_FAILED",
                    f"Docling 解析任务失败（{state}）",
                    retryable=False,
                )
            if state in _TASK_SUCCESS_STATES:
                return self._request_json(
                    "GET",
                    f"{self.base_url}/v1/result/{task_id}",
                    timeout_seconds=self.timeout_seconds,
                )
            if time.monotonic() > deadline:
                raise ParserError(
                    "PARSER_TIMEOUT",
                    f"Docling 解析超过 {self.max_wait_seconds}s 未完成",
                    retryable=True,
                )
            payload = self._request_json(
                "GET",
                f"{self.base_url}/v1/status/poll/{task_id}",
                # The server holds the long-poll connection up to ``wait``
                # seconds — a plain per-call timeout would false-trigger.
                timeout_seconds=self.timeout_seconds + self.poll_interval_seconds,
                params={"wait": self.poll_interval_seconds},
            )
            state = self._task_state(payload)
            if state not in _TASK_SUCCESS_STATES and state not in _TASK_FAILURE_STATES:
                # Pacing safety for servers that ignore ``wait``; costs at most
                # one extra interval per cycle against a 600s deadline.
                time.sleep(self.poll_interval_seconds)

    # -- Payload interpretation (single point of change) ------------------------

    @staticmethod
    def _task_state(payload: dict) -> str:
        return str(payload.get("task_status") or payload.get("state") or "").lower()

    @staticmethod
    def _extract_task_id(payload: dict) -> str | None:
        for key in ("task_id", "taskId"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _extract_result(payload: dict) -> DoclingResult:
        if str(payload.get("status") or "").lower() == "failure":
            errors = payload.get("errors")
            detail = "; ".join(str(item) for item in errors) if errors else "未知原因"
            raise ParserError(
                "PARSER_FAILED", f"Docling 转换失败：{detail}", retryable=False
            )
        document = payload.get("document")
        if not isinstance(document, dict):
            raise ParserError(
                "PARSER_RESPONSE_INVALID", "Docling 响应中缺少 document 结果"
            )
        markdown = document.get("md_content")
        if not (isinstance(markdown, str) and markdown.strip()):
            markdown = None
        docling_document = document.get("json_content")
        if not isinstance(docling_document, dict):
            docling_document = None
        if markdown is None and docling_document is None:
            raise ParserError(
                "PARSER_RESPONSE_INVALID",
                "Docling 响应中缺少 md_content 与 json_content",
            )
        return DoclingResult(markdown=markdown, docling_document=docling_document)


class DoclingParser(ParserAdapter):
    name = "DOCLING"
    version = "1.0"
    extensions = frozenset(
        {".pdf", ".docx", ".pptx", ".xlsx", ".png", ".jpg", ".jpeg", ".html", ".htm"}
    )
    mime_types = frozenset(
        {
            "application/pdf",
            "image/png",
            "image/jpeg",
            "text/html",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
    )

    def __init__(self, client: DoclingClient | None = None) -> None:
        self._client = client or DoclingClient.from_settings()

    def is_available(self) -> bool:
        return self._client.configured

    def parse(self, request: ParseRequest) -> ParsedDocument:
        source = request.source
        if not self.supports(source):
            raise ParserError("UNSUPPORTED_FILE_TYPE", "Docling 解析器不支持该文件类型")

        result = self._client.parse_file(
            source.file_name, source.content, source.mime_type
        )
        warnings: list[str] = []

        if result.docling_document is not None:
            blocks, page_count, block_warnings = self._blocks_from_document(
                result.docling_document
            )
            warnings.extend(block_warnings)
            markdown = result.markdown
            if markdown is None:
                markdown = markdown_from_blocks(blocks)
                warnings.append("Docling 未返回 markdown，已由结构化内容合成")
        else:
            markdown = result.markdown or ""
            blocks = split_markdown_blocks(markdown)
            page_count = 1 if markdown else 0
            warnings.append("Docling 未返回 json_content，已按 markdown 回退切分")

        return ParsedDocument(
            parser_name=self.name,
            parser_version=self.version,
            markdown=markdown,
            blocks=blocks,
            page_count=page_count,
            warnings=warnings,
        )

    @classmethod
    def _blocks_from_document(
        cls, doc: dict
    ) -> tuple[list[ParsedBlock], int | None, list[str]]:
        blocks: list[ParsedBlock] = []
        title_path: list[str] = []
        page_count: int | None = None
        skipped_images = 0
        visited: set[str] = set()
        walk_index = 0

        def resolve(ref: str) -> dict | None:
            # "#/texts/0" -> doc["texts"][0]; same for tables/pictures/groups
            parts = ref.lstrip("#/").split("/")
            if len(parts) != 2:
                return None
            pool, raw_index = parts
            try:
                index = int(raw_index)
            except ValueError:
                return None
            items = doc.get(pool)
            if isinstance(items, list) and 0 <= index < len(items):
                item = items[index]
                return item if isinstance(item, dict) else None
            return None

        def caption_text(item: dict) -> str:
            parts: list[str] = []
            for ref in item.get("captions") or []:
                target = (
                    resolve(str(ref.get("$ref") or "")) if isinstance(ref, dict) else None
                )
                if target:
                    text = str(target.get("text") or "").strip()
                    if text:
                        parts.append(text)
            return " ".join(parts)

        def page_no_of(item: dict) -> int | None:
            prov = item.get("prov")
            if isinstance(prov, list) and prov and isinstance(prov[0], dict):
                value = prov[0].get("page_no")
                if isinstance(value, int) and value >= 1:
                    return value
            return None

        def emit(content: str, item: dict, item_index: int) -> None:
            nonlocal page_count
            page_no = page_no_of(item)
            if page_no is not None:
                page_count = max(page_count or 0, page_no)
            blocks.append(
                ParsedBlock(
                    index=len(blocks),
                    content=content,
                    page_no=page_no,
                    title_path=list(title_path),
                    source_locator={
                        "pageNo": page_no,
                        "blockIndex": item_index,
                        "selfRef": item.get("self_ref"),
                    },
                )
            )

        def visit(ref_str: str) -> None:
            nonlocal walk_index, skipped_images, title_path
            # The body is a tree by contract, but this is untrusted JSON — a
            # ref cycle must not hang the worker.
            if not ref_str or ref_str in visited:
                return
            visited.add(ref_str)
            item = resolve(ref_str)
            if item is None:
                return
            item_index = walk_index
            walk_index += 1

            if ref_str.startswith("#/groups"):
                for child in item.get("children") or []:
                    child_ref = child.get("$ref") if isinstance(child, dict) else None
                    if isinstance(child_ref, str):
                        visit(child_ref)
                return

            label = str(item.get("label") or "")
            if label in _SKIP_LABELS:
                return

            if ref_str.startswith("#/tables"):
                content = cls._table_markdown(item, caption_text(item))
                if content:
                    emit(content, item, item_index)
                return

            if ref_str.startswith("#/pictures"):
                caption = caption_text(item)
                if caption:
                    emit(f"[图片] {caption}", item, item_index)
                else:
                    skipped_images += 1
                return

            text = str(item.get("text") or "").strip()
            if not text:
                return
            if label == "title":
                title_path = [text]
                return
            if label == "section_header":
                level = item.get("level")
                level = level if isinstance(level, int) and level >= 1 else 1
                # title occupies depth 0, section levels stack beneath it
                title_path = title_path[:level] + [text]
                return
            # text / list_item / code / formula — and unknown labels with
            # text also emit (drift shield for label-vocab changes)
            emit(text, item, item_index)

        body = doc.get("body")
        children = body.get("children") if isinstance(body, dict) else None
        for child in children or []:
            child_ref = child.get("$ref") if isinstance(child, dict) else None
            if isinstance(child_ref, str):
                visit(child_ref)

        warnings: list[str] = []
        if skipped_images:
            warnings.append(f"跳过 {skipped_images} 张无描述图片")
        return blocks, page_count, warnings

    @classmethod
    def _table_markdown(cls, item: dict, caption: str) -> str:
        lines: list[str] = []
        if caption:
            lines.append(caption)
        grid = (item.get("data") or {}).get("grid")
        rows: list[str] = []
        width = 0
        if isinstance(grid, list):
            for raw_row in grid:
                if not isinstance(raw_row, list):
                    continue
                cells = [
                    cls._cell(str(cell.get("text") or "")) if isinstance(cell, dict) else ""
                    for cell in raw_row
                ]
                width = max(width, len(cells))
                rows.append("| " + " | ".join(cells) + " |")
        if rows:
            lines.append(rows[0])
            lines.append("| " + " | ".join("---" for _ in range(max(width, 1))) + " |")
            lines.extend(rows[1:])
        return "\n".join(lines)

    @staticmethod
    def _cell(value: str) -> str:
        return " ".join(value.split()).replace("|", "\\|")
