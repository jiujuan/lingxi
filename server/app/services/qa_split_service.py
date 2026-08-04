from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
import re
import unicodedata

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from server.app.core.errors import not_found
from server.app.core.config import settings
from server.app.core import metrics
from server.app.core.ids import current_request_id
from server.app.core.log_redaction import redact_log_payload
from server.app.core.secrets import decrypt_secret
import server.app.db.base  # noqa: F401
from server.app.integrations.model_providers.base import ProviderError
from server.app.integrations.model_providers.registry import (
    ProviderFactory,
    build_provider_adapter,
)
from server.app.models.document import Document, DocumentStatus
from server.app.models.import_job import ImportJob, ImportJobStatus
from server.app.models.logs import TaskRun
from server.app.models.model_config import (
    ModelCallLog,
    ModelCapability,
    ModelConfig,
    ModelProvider,
)
from server.app.models.qa_pair import DocumentChunk, QaPair
from server.app.services._batching import run_ordered
from server.app.services.chunking import TokenCounter
from server.app.services.import_service import enqueue_embedding_task  # re-exported
from server.app.services.qa_split_backpressure import (
    BackpressureState,
    get_backpressure_state,
    run_ordered_with_backpressure,
)
from server.app.services.qa_split_batching import (
    QA_SPLIT_BATCH_CONFIG_INVALID,
    QaBatch,
    QaBatchResult,
    QaBatchingError,
    execute_qa_batch_with_retry,
    group_qa_chunks,
    qa_batch_input_hash,
)
from server.app.services.qa_prompt_builder import build_qa_split_prompt
from server.app.services.qa_split_run_service import QaSplitRunService

logger = logging.getLogger(__name__)

QA_PROVENANCE_MISSING_CHUNK_INDEX = "QA_PROVENANCE_MISSING_CHUNK_INDEX"
QA_PROVENANCE_UNKNOWN_CHUNK_INDEX = "QA_PROVENANCE_UNKNOWN_CHUNK_INDEX"
QA_PROVENANCE_QUOTE_MISMATCH = "QA_PROVENANCE_QUOTE_MISMATCH"
QA_PROVENANCE_COVERAGE_MISMATCH = "QA_PROVENANCE_COVERAGE_MISMATCH"
QA_PROVENANCE_CONTRACT_INVALID = "QA_PROVENANCE_CONTRACT_INVALID"
QA_PROVENANCE_INVALID_JSON = "QA_PROVENANCE_INVALID_JSON"
QA_PROVENANCE_ITEM_NOT_OBJECT = "QA_PROVENANCE_ITEM_NOT_OBJECT"
QA_PROVENANCE_EMPTY_REQUIRED_FIELD = "QA_PROVENANCE_EMPTY_REQUIRED_FIELD"
QA_PROVENANCE_INVALID_PAGE_NO = "QA_PROVENANCE_INVALID_PAGE_NO"
QA_PROVENANCE_EMPTY_ITEMS = "QA_PROVENANCE_EMPTY_ITEMS"
QA_PROVENANCE_NO_SPLITTABLE_CHUNKS = "QA_PROVENANCE_NO_SPLITTABLE_CHUNKS"
QA_PROVENANCE_SOURCE_CONFIG_INVALID = "QA_PROVENANCE_SOURCE_CONFIG_INVALID"
QA_PROVENANCE_MODEL_NOT_CONFIGURED = "QA_PROVENANCE_MODEL_NOT_CONFIGURED"

__all__ = [
    "QaSplitService",
    "QaSplitValidationError",
    "ValidatedQaItem",
    "validate_qa_split_output",
    "enqueue_embedding_task",
]


@dataclass(frozen=True)
class ValidatedQaItem:
    question: str
    answer: str
    quote: str
    page_no: int
    chunk_index: int | None = None


class QaSplitValidationError(Exception):
    def __init__(
        self,
        message: str,
        code: str = "QA_SPLIT_INVALID_OUTPUT",
        *,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _all_qa_batch_results(result: QaBatchResult) -> tuple[QaBatchResult, ...]:
    """Return a split root and all descendants for safe call-log diagnostics."""

    descendants: list[QaBatchResult] = [result]
    for child in result.split_results:
        descendants.extend(_all_qa_batch_results(child))
    return tuple(descendants)


def _batch_result_error(result: QaBatchResult) -> QaSplitValidationError:
    """Prevent Celery from replaying successful batches after policy exhaustion."""

    error = result.error
    assert error is not None
    code = getattr(error, "code", None)
    message = getattr(error, "message", None)
    return QaSplitValidationError(
        message if isinstance(message, str) else "QA Batch 调用失败",
        code=code if isinstance(code, str) else "QA_SPLIT_PROVIDER_ERROR",
        retryable=False,
    )


def _extract_json_text(raw_output: str) -> str:
    """Best-effort extraction of a JSON document from a model's raw text.

    The Ollama adapter asks for strict JSON (``format=json``), but that only
    covers Ollama, and even then some chatty models still wrap the object in a
    ```json fence or emit a sentence before it. This strips a surrounding
    Markdown code fence and, failing that, slices from the first opening bracket
    to its matching closing bracket so the common "prose around JSON" case still
    parses instead of failing the whole document.
    """
    text = raw_output.strip()
    if not text:
        return text
    # Strip a surrounding ```json ... ``` (or bare ```) fence.
    if text.startswith("```"):
        newline = text.find("\n")
        if newline != -1:
            text = text[newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    if text.startswith(("{", "[")):
        return text
    # Fall back to slicing the outermost object/array out of surrounding prose.
    starts = [pos for pos in (text.find("{"), text.find("[")) if pos != -1]
    if not starts:
        return text
    start = min(starts)
    close_char = "}" if text[start] == "{" else "]"
    end = text.rfind(close_char)
    return text[start : end + 1] if end > start else text


_WHITESPACE_RE = re.compile(r"\s+")


def _json_type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def _provenance_error(
    code: str,
    message: str,
    *,
    retryable: bool = True,
    metric_reason: str | None = None,
) -> QaSplitValidationError:
    metrics.observe_qa_provenance_validation_failure(metric_reason or code)
    return QaSplitValidationError(message, code=code, retryable=retryable)


def log_qa_split_observability(
    *,
    tenant_id: str,
    document_id: str,
    job_id: str,
    chunks: list[DocumentChunk],
    items: list[ValidatedQaItem],
) -> None:
    """Log QA-generation provenance metadata without prompt or QA content."""

    source_indexes = {chunk.chunk_index for chunk in chunks}
    covered_indexes = {
        item.chunk_index for item in items if item.chunk_index in source_indexes
    }
    coverage_ratio = len(covered_indexes) / len(source_indexes) if source_indexes else 0.0
    config_hashes = {
        chunk.chunker_config_hash
        for chunk in chunks
        if isinstance(chunk.chunker_config_hash, str) and chunk.chunker_config_hash
    }
    config_hash = next(iter(config_hashes)) if len(config_hashes) == 1 else None
    metrics.observe_qa_chunk_coverage_ratio(coverage_ratio)
    logger.info(
        "qa split completed",
        extra={
            "tenant_id": tenant_id,
            "document_id": document_id,
            "job_id": job_id,
            "config_hash": config_hash,
            "source_chunk_count": len(source_indexes),
            "covered_chunk_count": len(covered_indexes),
            "qa_pair_count": len(items),
            "coverage_ratio": round(coverage_ratio, 6),
        },
    )


def _normalized_quote(value: str) -> str:
    """Normalize only for containment checks; persisted quotes remain unchanged."""

    return _WHITESPACE_RE.sub(" ", unicodedata.normalize("NFC", value)).strip()


def _chunk_page_range(chunk: DocumentChunk) -> tuple[int, int]:
    start = chunk.page_start
    if start is None:
        start = chunk.page_no
    if start is None:
        start = 1
    end = chunk.page_end
    if end is None:
        end = start
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or start < 1
        or end < start
    ):
        raise _provenance_error(
            QA_PROVENANCE_CONTRACT_INVALID,
            "当前 Chunk 页码范围不合法",
            retryable=False,
        )
    return start, end


def _is_valid_chunk_index(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_item_fields(item: object, position: int) -> ValidatedQaItem:
    if not isinstance(item, dict):
        raise _provenance_error(
            QA_PROVENANCE_CONTRACT_INVALID,
            f"第 {position + 1} 个 QA 项不是对象",
            retryable=False,
            metric_reason=QA_PROVENANCE_ITEM_NOT_OBJECT,
        )
    question_value = item.get("question")
    answer_value = item.get("answer")
    quote = item.get("quote")
    if not all(isinstance(value, str) for value in (question_value, answer_value, quote)):
        raise _provenance_error(
            QA_PROVENANCE_CONTRACT_INVALID,
            "QA 项 question、answer 和 quote 必须是 JSON string",
            retryable=False,
        )
    question = question_value.strip()
    answer = answer_value.strip()
    page_no = item.get("pageNo", item.get("page_no"))
    chunk_index = item.get("chunkIndex", item.get("chunk_index"))
    if not question or not answer or not quote.strip():
        raise _provenance_error(
            QA_PROVENANCE_CONTRACT_INVALID,
            "QA 项缺少 question、answer 或 quote",
            retryable=False,
            metric_reason=QA_PROVENANCE_EMPTY_REQUIRED_FIELD,
        )
    if not isinstance(page_no, int) or isinstance(page_no, bool) or page_no < 1:
        raise _provenance_error(
            QA_PROVENANCE_CONTRACT_INVALID,
            "QA 项缺少合法 pageNo",
            retryable=False,
            metric_reason=QA_PROVENANCE_INVALID_PAGE_NO,
        )
    if chunk_index is not None and not _is_valid_chunk_index(chunk_index):
        raise _provenance_error(
            QA_PROVENANCE_CONTRACT_INVALID,
            "QA 项 chunkIndex 不合法",
            retryable=False,
        )
    return ValidatedQaItem(
        question=question,
        answer=answer,
        quote=quote,
        page_no=page_no,
        chunk_index=chunk_index,
    )


def _resolve_legacy_chunk_index(
    item: ValidatedQaItem,
    chunk_by_index: dict[int, DocumentChunk],
) -> int:
    normalized_quote = _normalized_quote(item.quote)
    matches = [
        chunk_index
        for chunk_index, chunk in chunk_by_index.items()
        if _chunk_page_range(chunk)[0] <= item.page_no <= _chunk_page_range(chunk)[1]
        and normalized_quote in _normalized_quote(chunk.content or "")
    ]
    if len(matches) != 1:
        raise _provenance_error(
            QA_PROVENANCE_MISSING_CHUNK_INDEX,
            "缺少 chunkIndex 的旧 QA 输出无法唯一关联到当前批次 Chunk",
        )
    return matches[0]


def _validate_coverage_partition(
    parsed: dict,
    item_indexes: set[int],
    expected_indexes: set[int],
) -> None:
    covered = parsed.get("coveredChunkIndexes")
    skipped = parsed.get("skippedChunks")
    if not isinstance(covered, list) or not isinstance(skipped, list):
        raise _provenance_error(
            QA_PROVENANCE_COVERAGE_MISMATCH,
            "QA 拆分输出必须包含 coveredChunkIndexes 和 skippedChunks",
        )
    if any(not _is_valid_chunk_index(index) for index in covered):
        raise _provenance_error(
            QA_PROVENANCE_COVERAGE_MISMATCH,
            "coveredChunkIndexes 包含不合法 index",
        )
    covered_indexes = set(covered)
    if len(covered_indexes) != len(covered):
        raise _provenance_error(
            QA_PROVENANCE_COVERAGE_MISMATCH,
            "coveredChunkIndexes 不能包含重复 index",
        )
    if not covered_indexes <= expected_indexes:
        raise _provenance_error(
            QA_PROVENANCE_COVERAGE_MISMATCH,
            "coveredChunkIndexes 包含当前 Batch 之外的 index",
        )

    skipped_indexes: set[int] = set()
    for skipped_item in skipped:
        if not isinstance(skipped_item, dict):
            raise _provenance_error(
                QA_PROVENANCE_COVERAGE_MISMATCH,
                "skippedChunks 必须包含对象",
            )
        chunk_index = skipped_item.get("chunkIndex", skipped_item.get("chunk_index"))
        reason = skipped_item.get("reason")
        if not _is_valid_chunk_index(chunk_index):
            raise _provenance_error(
                QA_PROVENANCE_COVERAGE_MISMATCH,
                "skippedChunks 包含不合法 chunkIndex",
            )
        if not isinstance(reason, str) or not reason.strip():
            raise _provenance_error(
                QA_PROVENANCE_COVERAGE_MISMATCH,
                "skippedChunks 的 reason 不能为空",
            )
        if chunk_index in skipped_indexes:
            raise _provenance_error(
                QA_PROVENANCE_COVERAGE_MISMATCH,
                "skippedChunks 不能包含重复 index",
            )
        skipped_indexes.add(chunk_index)
    if not skipped_indexes <= expected_indexes:
        raise _provenance_error(
            QA_PROVENANCE_COVERAGE_MISMATCH,
            "skippedChunks 包含当前 Batch 之外的 index",
        )
    if covered_indexes & skipped_indexes:
        raise _provenance_error(
            QA_PROVENANCE_COVERAGE_MISMATCH,
            "coveredChunkIndexes 与 skippedChunks 不能重叠",
        )
    if covered_indexes | skipped_indexes != expected_indexes:
        raise _provenance_error(
            QA_PROVENANCE_COVERAGE_MISMATCH,
            "covered/skipped 未对当前 Batch 构成完备分区",
        )
    if item_indexes != covered_indexes:
        raise _provenance_error(
            QA_PROVENANCE_COVERAGE_MISMATCH,
            "items 的 chunkIndex 必须与 coveredChunkIndexes 一致",
        )


def validate_qa_split_output(
    raw_output: str,
    chunks: list[DocumentChunk] | None = None,
    *,
    allow_legacy_missing_chunk_index: bool = False,
) -> list[ValidatedQaItem]:
    try:
        parsed = json.loads(_extract_json_text(raw_output))
    except json.JSONDecodeError as exc:
        raise _provenance_error(
            "QA_SPLIT_INVALID_OUTPUT",
            "QA 拆分模型输出不是合法 JSON",
            retryable=False,
            metric_reason=QA_PROVENANCE_INVALID_JSON,
        ) from exc

    if not isinstance(parsed, dict):
        raise _provenance_error(
            QA_PROVENANCE_CONTRACT_INVALID,
            "QA 拆分输出必须是 JSON object",
            retryable=False,
        )
    if "items" not in parsed:
        raise _provenance_error(
            QA_PROVENANCE_CONTRACT_INVALID,
            "QA 拆分输出缺少 items 数组",
            retryable=False,
        )
    items = parsed.get("items")
    if not isinstance(items, list):
        raise _provenance_error(
            QA_PROVENANCE_CONTRACT_INVALID,
            (
                "QA 拆分输出 items 必须是数组，"
                f"实际类型为 {_json_type_name(items)}"
            ),
            retryable=False,
        )

    validated = [_validate_item_fields(item, index) for index, item in enumerate(items)]
    if chunks is None:
        if not validated:
            raise _provenance_error(
                QA_PROVENANCE_CONTRACT_INVALID,
                "QA 拆分输出 items 为空",
                retryable=False,
                metric_reason=QA_PROVENANCE_EMPTY_ITEMS,
            )
        return validated

    chunk_by_index = {chunk.chunk_index: chunk for chunk in chunks}
    expected_indexes = set(chunk_by_index)
    if len(chunk_by_index) != len(chunks):
        raise _provenance_error(
            QA_PROVENANCE_CONTRACT_INVALID,
            "当前 Batch 存在重复 chunkIndex",
            retryable=False,
        )
    if not expected_indexes:
        raise _provenance_error(
            QA_PROVENANCE_CONTRACT_INVALID,
            "当前 Batch 没有可验证的 Chunk",
            retryable=False,
        )

    if (
        not allow_legacy_missing_chunk_index
        and any(item.chunk_index is None for item in validated)
    ):
        raise _provenance_error(
            QA_PROVENANCE_MISSING_CHUNK_INDEX,
            "QA 项缺少 chunkIndex",
        )

    strict_coverage = (
        "coveredChunkIndexes" in parsed or "skippedChunks" in parsed
    )
    if not strict_coverage and not allow_legacy_missing_chunk_index:
        raise _provenance_error(
            QA_PROVENANCE_COVERAGE_MISMATCH,
            "QA 拆分输出必须包含 coveredChunkIndexes 和 skippedChunks",
        )

    resolved: list[ValidatedQaItem] = []
    compatibility_used = False
    for item in validated:
        chunk_index = item.chunk_index
        if chunk_index is None:
            if not allow_legacy_missing_chunk_index:
                raise _provenance_error(
                    QA_PROVENANCE_MISSING_CHUNK_INDEX,
                    "QA 项缺少 chunkIndex",
                )
            chunk_index = _resolve_legacy_chunk_index(item, chunk_by_index)
            compatibility_used = True
        chunk = chunk_by_index.get(chunk_index)
        if chunk is None:
            # Explicit unknown indexes are always rejected, including compat mode.
            raise _provenance_error(
                QA_PROVENANCE_UNKNOWN_CHUNK_INDEX,
                "QA 项 chunkIndex 不属于当前 Batch",
            )
        page_start, page_end = _chunk_page_range(chunk)
        if not page_start <= item.page_no <= page_end:
            raise _provenance_error(
                QA_PROVENANCE_QUOTE_MISMATCH,
                "QA 项 pageNo 不在其 Chunk 页码范围内",
            )
        if _normalized_quote(item.quote) not in _normalized_quote(chunk.content or ""):
            raise _provenance_error(
                QA_PROVENANCE_QUOTE_MISMATCH,
                "QA 项 quote 不属于其指向 Chunk",
            )
        resolved.append(
            ValidatedQaItem(
                question=item.question,
                answer=item.answer,
                quote=item.quote,
                page_no=item.page_no,
                chunk_index=chunk_index,
            )
        )

    item_indexes = {item.chunk_index for item in resolved if item.chunk_index is not None}
    if strict_coverage:
        _validate_coverage_partition(parsed, item_indexes, expected_indexes)
    elif item_indexes != expected_indexes:
        raise _provenance_error(
            QA_PROVENANCE_COVERAGE_MISMATCH,
            "旧 QA 输出未覆盖当前 Batch 的全部 Chunk，拒绝不完整关联",
        )
    if compatibility_used:
        logger.info(
            "qa_provenance_legacy_compatibility_total",
            extra={"result": "accepted"},
        )
    return resolved


class QaSplitService:
    def __init__(
        self,
        session: Session,
        provider_factory: ProviderFactory = build_provider_adapter,
        *,
        legacy_missing_chunk_index_compatibility: bool = False,
        token_counter: TokenCounter | None = None,
        max_input_tokens: int | None = None,
        reserved_output_tokens: int | None = None,
        max_batch_chars: int | None = None,
        max_concurrency: int | None = None,
        initial_concurrency: int | None = None,
        min_concurrency: int | None = None,
        max_retries: int | None = None,
        max_split_depth: int | None = None,
    ) -> None:
        self.session = session
        self._build_adapter = provider_factory
        # Task 16 owns runtime feature-flag wiring. Keeping this constructor
        # injected prevents the task path from reading environment variables.
        self.legacy_missing_chunk_index_compatibility = (
            legacy_missing_chunk_index_compatibility
        )
        # The service factory resolves these inputs for production. Defaults
        # preserve direct construction in focused legacy tests.
        self.token_counter = token_counter
        self.max_input_tokens = (
            max_input_tokens
            if max_input_tokens is not None
            else getattr(settings, "qa_split_max_input_tokens", 4096)
        )
        self.reserved_output_tokens = (
            reserved_output_tokens
            if reserved_output_tokens is not None
            else getattr(settings, "qa_split_reserved_output_tokens", 2048)
        )
        self.max_batch_chars = (
            max_batch_chars
            if max_batch_chars is not None
            else getattr(settings, "qa_split_max_batch_chars", 6000)
        )
        self.max_concurrency = (
            max_concurrency
            if max_concurrency is not None
            else getattr(settings, "qa_split_max_concurrency", 4)
        )
        self.initial_concurrency = (
            initial_concurrency
            if initial_concurrency is not None
            else getattr(settings, "qa_split_initial_concurrency", 1)
        )
        self.min_concurrency = (
            min_concurrency
            if min_concurrency is not None
            else getattr(settings, "qa_split_min_concurrency", 1)
        )
        self.max_retries = (
            max_retries
            if max_retries is not None
            else getattr(settings, "qa_split_max_retries", 1)
        )
        self.max_split_depth = (
            max_split_depth
            if max_split_depth is not None
            else getattr(settings, "qa_split_max_split_depth", 1)
        )
        if (
            not isinstance(self.max_input_tokens, int)
            or isinstance(self.max_input_tokens, bool)
            or self.max_input_tokens <= 0
            or not isinstance(self.reserved_output_tokens, int)
            or isinstance(self.reserved_output_tokens, bool)
            or self.reserved_output_tokens < 0
            or not isinstance(self.max_retries, int)
            or isinstance(self.max_retries, bool)
            or self.max_retries < 0
            or not isinstance(self.max_split_depth, int)
            or isinstance(self.max_split_depth, bool)
            or self.max_split_depth < 0
            or not isinstance(self.initial_concurrency, int)
            or isinstance(self.initial_concurrency, bool)
            or self.initial_concurrency <= 0
            or not isinstance(self.min_concurrency, int)
            or isinstance(self.min_concurrency, bool)
            or self.min_concurrency <= 0
            or not isinstance(self.max_concurrency, int)
            or isinstance(self.max_concurrency, bool)
            or self.max_concurrency <= 0
        ):
            raise QaSplitValidationError(
                "QA token budget 配置不合法",
                code=QA_SPLIT_BATCH_CONFIG_INVALID,
                retryable=False,
            )

    def _get_qa_backpressure_state(
        self,
        provider: ModelProvider,
        model_config: ModelConfig,
    ) -> BackpressureState:
        """Resolve provider options and return an isolated adaptive state."""

        system_max = max(1, int(self.max_concurrency))
        minimum = min(max(1, int(self.min_concurrency)), system_max)
        provider_qa = (provider.config or {}).get("qaSplit", {})
        model_qa = (model_config.config or {}).get("qaSplit", {})
        if not isinstance(provider_qa, dict):
            provider_qa = {}
        if not isinstance(model_qa, dict):
            model_qa = {}
        configured_max = model_qa.get("maxConcurrency", provider_qa.get("maxConcurrency"))
        has_explicit_max = configured_max is not None
        try:
            configured_max = int(configured_max) if has_explicit_max else system_max
        except (TypeError, ValueError):
            configured_max = system_max
        effective_max = min(system_max, max(1, configured_max))
        minimum = min(minimum, effective_max)
        initial = self.initial_concurrency
        if provider.provider_type == "OLLAMA" and not has_explicit_max:
            initial = 1
        initial = min(effective_max, max(minimum, int(initial)))
        return get_backpressure_state(
            provider.id,
            model_config.id,
            current_concurrency=initial,
            min_concurrency=minimum,
            max_concurrency=effective_max,
        )

    def split_import_job(self, job_id: str) -> ImportJob:
        job, _task_run_id = self.split_import_job_for_task(job_id)
        return job

    def split_import_job_for_task(self, job_id: str) -> tuple[ImportJob, str | None]:
        """Run QA splitting and return the exact TaskRun created for this invocation."""
        job = self.session.get(ImportJob, job_id)
        if job is None:
            raise ValueError("Import job does not exist")
        document = self.session.get(Document, job.document_id)
        if document is None:
            raise ValueError("Import job document does not exist")

        # Idempotency: a duplicate delivery of an already-finished job is a no-op.
        if job.status == ImportJobStatus.COMPLETED.value:
            return job, None

        task_run = TaskRun(
            tenant_id=job.tenant_id,
            task_type="split_document_qa_task",
            queue_name="qa",
            resource_type="IMPORT_JOB",
            resource_id=job.id,
            stage="QA_SPLITTING",
            status="RUNNING",
            error=None,
            request_id=None,
        )
        self.session.add(task_run)
        self.session.flush()

        job.status = ImportJobStatus.RUNNING.value
        job.stage = "QA_SPLITTING"
        job.progress = max(job.progress, 45)
        document.status = DocumentStatus.QA_SPLITTING
        self.session.flush()

        try:
            chunks = self._list_chunks(document.id)
            if not chunks:
                raise _provenance_error(
                    QA_PROVENANCE_NO_SPLITTABLE_CHUNKS,
                    "文档没有可拆分的 Chunk",
                    retryable=False,
                )
            model_config, provider = self._default_model(job.tenant_id)
            adapter = self._build_adapter(
                provider.provider_type,
                provider.base_url,
                decrypt_secret(provider.encrypted_api_key),
                {**(provider.config or {}), **(model_config.config or {})},
                model_name=model_config.model_name,
                timeout_ms=model_config.timeout_ms,
                connect_timeout_ms=model_config.connect_timeout_ms,
                write_timeout_ms=model_config.write_timeout_ms,
                read_idle_timeout_ms=model_config.read_idle_timeout_ms,
                overall_timeout_ms=model_config.overall_timeout_ms,
                max_tokens=model_config.max_tokens,
                provider_name=provider.name,
            )
            prompt_batches = self._group_qa_batches(document, chunks)
            checkpoint = QaSplitRunService(
                self.session,
                replace_qa_pairs=self._replace_qa_pairs,
                bind_embedding_generation=self._bind_embedding_run_config_hash,
                default_model_resolver=self._default_model,
            )
            run = checkpoint.get_or_create_run(
                job=job,
                document=document,
                model_config=model_config,
                provider=provider,
                batches=prompt_batches,
                task_run_id=task_run.id,
            )
            batches_by_path = {
                ".".join(str(index) for index in batch.batch_index_path): batch
                for batch in prompt_batches
            }
            while batch := checkpoint.claim_next_pending_batch(run.id):
                prompt_batch = batches_by_path.get(batch.batch_index)
                if prompt_batch is None:
                    raise _provenance_error(
                        QA_PROVENANCE_CONTRACT_INVALID,
                        "QA checkpoint Batch 未找到对应的输入批次",
                        retryable=False,
                    )
                try:
                    batch_items, latency_ms = self._generate_checkpoint_batch(
                        adapter,
                        document,
                        prompt_batch,
                        model_config=model_config,
                        provider=provider,
                        run_id=task_run.id,
                    )
                except QaSplitValidationError as exc:
                    checkpoint.save_failure(
                        batch.id,
                        code=exc.code,
                        message=exc.message,
                        retryable=exc.retryable,
                        timeout_phase=None,
                    )
                    self.session.commit()
                    raise
                checkpoint.save_success(
                    batch.id,
                    batch_items,
                    latency_ms=latency_ms,
                )
                self.session.commit()

            items = checkpoint.publish_complete_run(
                run.id,
                job=job,
                document=document,
                chunks=chunks,
            )
            log_qa_split_observability(
                tenant_id=job.tenant_id,
                document_id=document.id,
                job_id=job.id,
                chunks=chunks,
                items=items,
            )

            document.qa_pair_count = len(items)
            document.status = DocumentStatus.EMBEDDING
            document.last_error_code = None
            document.last_error_message = None
            job.stage = "EMBEDDING"
            job.progress = 65
            job.status = ImportJobStatus.RUNNING.value
            job.error_code = None
            job.error_message = None
            task_run.status = "SUCCESS"
            task_run.error = None
            self.session.commit()
            return job, task_run.id
        except QaSplitValidationError as exc:
            self._mark_failed(
                # Existing task delivery semantics do not replay a complete QA
                # job after batch policy exhaustion. The checkpoint remains
                # retryable and a later delivery resumes only that Batch.
                job, document, task_run, exc.code, exc.message, False
            )
            return job, task_run.id
        except ProviderError as exc:
            # ProviderError is a normalized, safe error contract. Preserve its
            # code and retryability so Celery does not waste retries on permanent
            # provider failures (for example, 401/400), while transient failures
            # such as timeouts can still retry.
            logger.warning(
                "qa split provider failure code=%s job_id=%s document_id=%s",
                exc.code,
                job.id,
                document.id,
            )
            self._mark_failed(
                job, document, task_run, exc.code, exc.message, exc.retryable
            )
            return job, task_run.id
        except Exception:
            logger.error(
                "qa split failed code=%s job_id=%s document_id=%s",
                "QA_SPLIT_INTERNAL_ERROR",
                job.id,
                document.id,
            )
            self._mark_failed(
                job,
                document,
                task_run,
                "QA_SPLIT_INTERNAL_ERROR",
                "QA 拆分失败",
                True,
            )
            return job, task_run.id

    def mark_embedding_enqueue_failed(self, job_id: str, task_run_id: str) -> ImportJob:
        """Persist a retryable task failure after QA succeeds but broker enqueue fails."""
        job = self.session.get(ImportJob, job_id)
        if job is None:
            raise ValueError("Import job does not exist")
        document = self.session.get(Document, job.document_id)
        if document is None:
            raise ValueError("Import job document does not exist")
        task_run = self.session.get(TaskRun, task_run_id)
        if (
            task_run is None
            or task_run.tenant_id != job.tenant_id
            or task_run.task_type != "split_document_qa_task"
            or task_run.resource_type != "IMPORT_JOB"
            or task_run.resource_id != job.id
        ):
            raise ValueError("QA TaskRun does not match import job")
        self._mark_failed(
            job,
            document,
            task_run,
            "EMBEDDING_ENQUEUE_FAILED",
            "Embedding 任务入队失败",
            True,
        )
        return job

    def regenerate_document(self, tenant_id: str, document_id: str) -> ImportJob:
        job = self.session.scalar(
            select(ImportJob)
            .where(
                ImportJob.tenant_id == tenant_id,
                ImportJob.document_id == document_id,
                ImportJob.deleted_at.is_(None),
            )
            .order_by(ImportJob.created_at.desc())
        )
        if job is None:
            raise not_found("文档导入任务不存在")
        return self.split_import_job(job.id)

    def _default_model(self, tenant_id: str) -> tuple[ModelConfig, ModelProvider]:
        statement = (
            select(ModelConfig, ModelProvider)
            .join(ModelProvider, ModelProvider.id == ModelConfig.provider_id)
            .where(
                ModelConfig.tenant_id == tenant_id,
                ModelConfig.capability == ModelCapability.QA_SPLIT.value,
                ModelConfig.is_default.is_(True),
                ModelConfig.status == "ACTIVE",
                ModelConfig.deleted_at.is_(None),
                ModelProvider.status == "ACTIVE",
                ModelProvider.deleted_at.is_(None),
            )
        )
        row = self.session.execute(statement).first()
        if row is None:
            raise _provenance_error(
                "QA_SPLIT_MODEL_NOT_CONFIGURED",
                "未配置默认 QA Split 模型",
                # Deterministic config gap: auto-retry can't help until an admin
                # configures a default QA_SPLIT model, so don't burn retries.
                retryable=False,
                metric_reason=QA_PROVENANCE_MODEL_NOT_CONFIGURED,
            )
        return row[0], row[1]

    def _group_qa_batches(
        self,
        document: Document,
        chunks: list[DocumentChunk],
    ) -> list[QaBatch]:
        """Use token budgets when injected, with chars retained as a fallback."""

        if self.token_counter is not None:
            try:
                return group_qa_chunks(
                    document,
                    chunks,
                    token_counter=self.token_counter,
                    max_input_tokens=self.max_input_tokens,
                    reserved_output_tokens=self.reserved_output_tokens,
                )
            except QaBatchingError as exc:
                raise _provenance_error(
                    exc.code,
                    exc.message,
                    retryable=exc.retryable,
                ) from exc

        groups = self._group_chunks(sorted(chunks, key=lambda chunk: chunk.chunk_index))
        return [
            QaBatch(
                batch_index=index,
                chunks=tuple(group),
                estimated_input_tokens=0,
                reserved_output_tokens=self.reserved_output_tokens,
                input_hash=qa_batch_input_hash(group),
                budget_mode="chars_fallback",
            )
            for index, group in enumerate(groups)
        ]

    def _group_chunks(self, chunks: list[DocumentChunk]) -> list[list[DocumentChunk]]:
        """Group chunks so each QA-split prompt stays within a size budget.

        A single document can hold far more text than a model's context window,
        so chunks are packed greedily into groups bounded by
        ``qa_split_max_batch_chars`` (an approximate token proxy). A chunk larger
        than the budget forms its own group.
        """
        max_chars = max(1, self.max_batch_chars)
        groups: list[list[DocumentChunk]] = []
        current: list[DocumentChunk] = []
        current_chars = 0
        for chunk in chunks:
            chunk_chars = len(chunk.content or "")
            if (
                getattr(chunk, "chunker_name", "legacy_parser") == "adaptive_hierarchical"
                and chunk_chars > max_chars
            ):
                raise _provenance_error(
                    QA_PROVENANCE_CONTRACT_INVALID,
                    "Adaptive Chunk 超出 QA batch 字符预算",
                    retryable=False,
                )
            if current and current_chars + chunk_chars > max_chars:
                groups.append(current)
                current = []
                current_chars = 0
            current.append(chunk)
            current_chars += chunk_chars
        if current:
            groups.append(current)
        return groups

    def _generate_qa_items(
        self,
        adapter,
        document: Document,
        groups: list[list[DocumentChunk]] | list[QaBatch],
        *,
        model_config: ModelConfig | None = None,
        provider: ModelProvider | None = None,
        run_id: str | None = None,
    ) -> list[ValidatedQaItem]:
        """Run QA split per chunk-group (bounded concurrency) and merge results.

        Each group is generated and validated independently; because every chunk
        carries its global ``chunkIndex`` in the prompt, merged items still map
        back to the correct source chunk in order.
        """

        batches = [
            group
            if isinstance(group, QaBatch)
            else QaBatch(
                batch_index=index,
                chunks=tuple(group),
                estimated_input_tokens=0,
                reserved_output_tokens=self.reserved_output_tokens,
                input_hash=qa_batch_input_hash(group),
                budget_mode="legacy_group",
            )
            for index, group in enumerate(groups)
        ]

        class PromptBatchAdapter:
            def generate_qa_batch(self, batch: QaBatch) -> str:
                return adapter.generate_qa_pairs(
                    build_qa_split_prompt(document, list(batch.chunks))
                )

        prompt_batch_adapter = PromptBatchAdapter()

        def worker(batch: QaBatch) -> QaBatchResult:
            return execute_qa_batch_with_retry(
                prompt_batch_adapter,
                batch,
                max_retries=self.max_retries,
                max_split_depth=self.max_split_depth,
            )

        if provider is not None and model_config is not None:
            batch_results = run_ordered_with_backpressure(
                batches,
                worker,
                self._get_qa_backpressure_state(provider, model_config),
            )
        else:
            batch_results = run_ordered(batches, worker, self.max_concurrency)
        for result in batch_results:
            for leaf_result in _all_qa_batch_results(result):
                self._record_qa_model_call(
                    leaf_result.batch,
                    leaf_result,
                    model_config=model_config,
                    provider=provider,
                    run_id=run_id,
                    endpoint=getattr(adapter, "last_endpoint", None),
                    model_name_snapshot=getattr(adapter, "model_name", None),
                )
        leaf_results = sorted(
            (
                leaf_result
                for result in batch_results
                for leaf_result in result.leaf_results()
            ),
            key=lambda result: (
                result.batch.batch_index,
                result.batch.batch_index_path,
            ),
        )
        for result in leaf_results:
            if result.error is not None:
                raise _batch_result_error(result)

        items: list[ValidatedQaItem] = []
        for result in leaf_results:
            validated = validate_qa_split_output(
                result.raw_output or "",
                list(result.batch.chunks),
                allow_legacy_missing_chunk_index=(
                    self.legacy_missing_chunk_index_compatibility
                ),
            )
            items.extend(
                sorted(
                    validated,
                    key=lambda item: item.chunk_index
                    if item.chunk_index is not None
                    else -1,
                )
            )
        return items

    def _generate_checkpoint_batch(
        self,
        adapter,
        document: Document,
        batch: QaBatch,
        *,
        model_config: ModelConfig,
        provider: ModelProvider,
        run_id: str,
    ) -> tuple[list[ValidatedQaItem], int]:
        """Generate one persisted batch while retaining leaf-call diagnostics."""

        class PromptBatchAdapter:
            def generate_qa_batch(self, prompt_batch: QaBatch) -> str:
                return adapter.generate_qa_pairs(
                    build_qa_split_prompt(document, list(prompt_batch.chunks))
                )

        result = execute_qa_batch_with_retry(
            PromptBatchAdapter(),
            batch,
            max_retries=self.max_retries,
            max_split_depth=self.max_split_depth,
        )
        for leaf_result in _all_qa_batch_results(result):
            self._record_qa_model_call(
                leaf_result.batch,
                leaf_result,
                model_config=model_config,
                provider=provider,
                run_id=run_id,
                endpoint=getattr(adapter, "last_endpoint", None),
                model_name_snapshot=getattr(adapter, "model_name", None),
            )

        leaf_results = sorted(
            result.leaf_results(),
            key=lambda leaf: (leaf.batch.batch_index, leaf.batch.batch_index_path),
        )
        for leaf_result in leaf_results:
            if leaf_result.error is not None:
                error = leaf_result.error
                raise QaSplitValidationError(
                    getattr(error, "message", None) or "QA Batch 调用失败",
                    code=getattr(error, "code", None) or "QA_SPLIT_PROVIDER_ERROR",
                    retryable=bool(getattr(error, "retryable", False)),
                )

        items: list[ValidatedQaItem] = []
        for leaf_result in leaf_results:
            items.extend(
                validate_qa_split_output(
                    leaf_result.raw_output or "",
                    list(leaf_result.batch.chunks),
                    allow_legacy_missing_chunk_index=(
                        self.legacy_missing_chunk_index_compatibility
                    ),
                )
            )
        return items, sum(leaf_result.latency_ms for leaf_result in leaf_results)

    def _record_qa_model_call(
        self,
        batch: QaBatch,
        result: QaBatchResult,
        *,
        model_config: ModelConfig | None,
        provider: ModelProvider | None,
        run_id: str | None,
        endpoint: str | None = None,
        model_name_snapshot: str | None = None,
    ) -> None:
        if model_config is None or provider is None:
            return
        error = result.error
        if isinstance(error, ProviderError):
            error_code = error.code
            error_message = error.message
            error_endpoint = error.endpoint
            error_model_name = error.model_name
            timeout_phase = error.timeout_phase
        elif error is not None:
            error_code = "QA_SPLIT_PROVIDER_ERROR"
            error_message = "QA Split 模型调用失败"
            error_endpoint = None
            error_model_name = None
            timeout_phase = None
        else:
            error_code = None
            error_message = None
            error_endpoint = None
            error_model_name = None
            timeout_phase = None
        raw_output = result.raw_output if isinstance(result.raw_output, str) else None
        input_char_count = sum(
            len(chunk.content or "") for chunk in batch.chunks
        )
        estimated_output_tokens = None
        if raw_output is not None and self.token_counter is not None:
            estimated_output_tokens = self.token_counter.count(raw_output)
        self.session.add(
            ModelCallLog(
                tenant_id=model_config.tenant_id,
                provider_id=provider.id,
                model_config_id=model_config.id,
                run_id=run_id,
                capability=ModelCapability.QA_SPLIT.value,
                status="FAILED" if error is not None else "SUCCESS",
                latency_ms=result.latency_ms,
                token_usage={},
                batch_id=batch.batch_id,
                batch_index=".".join(
                    str(index) for index in batch.batch_index_path
                ),
                retry_count=result.retry_count,
                split_depth=batch.split_depth,
                input_char_count=input_char_count,
                estimated_input_tokens=batch.estimated_input_tokens,
                output_char_count=len(raw_output) if raw_output is not None else None,
                estimated_output_tokens=estimated_output_tokens,
                timeout_phase=timeout_phase,
                endpoint=redact_log_payload(
                    error_endpoint or endpoint or provider.base_url
                ),
                model_name_snapshot=(
                    error_model_name
                    or model_name_snapshot
                    or model_config.model_name
                ),
                error_code=error_code,
                error_message=redact_log_payload(error_message),
                request_id=current_request_id(),
            )
        )

    @staticmethod
    def _bind_embedding_run_config_hash(
        job: ImportJob, chunks: list[DocumentChunk]
    ) -> None:
        """Persist the exact Child generation that produced this QA run."""
        config_hashes = {
            chunk.chunker_config_hash.strip()
            for chunk in chunks
            if isinstance(chunk.chunker_config_hash, str) and chunk.chunker_config_hash.strip()
        }
        if len(config_hashes) != 1:
            raise _provenance_error(
                "QA_SPLIT_RUN_CONFIG_INVALID",
                "QA 来源 Chunk generation 无法唯一确定",
                metric_reason=QA_PROVENANCE_SOURCE_CONFIG_INVALID,
            )
        options = dict(job.options) if isinstance(job.options, dict) else {}
        embedding_options = options.get("embedding")
        options["embedding"] = {
            **(embedding_options if isinstance(embedding_options, dict) else {}),
            "run_config_hash": config_hashes.pop(),
        }
        # Reassignment (rather than mutating nested JSON) makes SQLAlchemy
        # persist this recoverable transition metadata on every backend.
        job.options = options

    def _list_chunks(self, document_id: str) -> list[DocumentChunk]:
        # Hierarchical chunking persists Parent and Child in the same table;
        # QA generation may only consume retrievable CHILD rows.  Select one
        # active config generation so stale/corrupt mixed generations cannot
        # create duplicate chunkIndex mappings.
        active_children = list(
            self.session.scalars(
                select(DocumentChunk)
                .where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.deleted_at.is_(None),
                    DocumentChunk.status == "ACTIVE",
                    DocumentChunk.chunk_level == "CHILD",
                )
                .order_by(DocumentChunk.created_at.desc(), DocumentChunk.id.desc())
            ).all()
        )
        if not active_children:
            return []
        config_hash = active_children[0].chunker_config_hash
        return sorted(
            (
                chunk
                for chunk in active_children
                if chunk.chunker_config_hash == config_hash
            ),
            key=lambda chunk: chunk.chunk_index,
        )

    def _replace_qa_pairs(
        self,
        job: ImportJob,
        document: Document,
        chunks: list[DocumentChunk],
        items: list[ValidatedQaItem],
    ) -> None:
        chunk_by_index = {chunk.chunk_index: chunk for chunk in chunks}
        resolved_chunks: list[tuple[int, ValidatedQaItem, DocumentChunk]] = []
        for index, item in enumerate(items):
            chunk = chunk_by_index.get(item.chunk_index)
            if chunk is None:
                raise _provenance_error(
                    QA_PROVENANCE_UNKNOWN_CHUNK_INDEX,
                    "QA 项未能关联到当前 Document Chunk",
                    retryable=False,
                )
            resolved_chunks.append((index, item, chunk))

        self.session.execute(delete(QaPair).where(QaPair.document_id == document.id))
        for index, item, chunk in resolved_chunks:
            self.session.add(
                QaPair(
                    tenant_id=job.tenant_id,
                    document_id=document.id,
                    chunk_id=chunk.id,
                    job_id=job.id,
                    pair_index=index,
                    question=item.question,
                    answer=item.answer,
                    quote=item.quote,
                    page_no=item.page_no,
                    question_embedding=None,
                    search_text="",
                    token_count=len(item.question.split()) + len(item.answer.split()),
                    status="ACTIVE",
                    qa_metadata={"sourceChunkIndex": chunk.chunk_index},
                )
            )

    def _mark_failed(
        self,
        job: ImportJob,
        document: Document,
        task_run: TaskRun,
        code: str,
        message: str,
        retryable: bool,
    ) -> None:
        document.status = DocumentStatus.FAILED
        document.last_error_code = code
        document.last_error_message = message
        job.status = ImportJobStatus.FAILED.value
        job.stage = job.stage or "QA_SPLITTING"
        job.error_code = code
        job.error_message = message
        task_run.stage = job.stage
        task_run.status = "FAILED"
        task_run.error = {
            "code": code,
            "message": message,
            "retryable": retryable,
            "failedAt": datetime.now(UTC).isoformat(),
        }
        self.session.commit()
