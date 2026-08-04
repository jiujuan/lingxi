"""Deterministic token-budget batching for QA split prompts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import hashlib
import json
from types import SimpleNamespace
import time
from typing import Sequence

from server.app.integrations.model_providers.base import ProviderError
from server.app.core import metrics
from server.app.models.document import Document
from server.app.models.qa_pair import DocumentChunk
from server.app.services.chunking import TokenCounter, TokenLimitError, TokenizerUnavailableError
from server.app.services.qa_prompt_builder import (
    QA_SPLIT_PROMPT_VERSION,
    estimate_qa_split_prompt_tokens,
)

QA_SPLIT_BATCH_CONFIG_INVALID = "QA_SPLIT_BATCH_CONFIG_INVALID"
QA_PROVENANCE_CONTRACT_INVALID = "QA_PROVENANCE_CONTRACT_INVALID"
RETRYABLE_QA_CODES = frozenset(
    {
        "PROVIDER_CONNECTION_TIMEOUT",
        "PROVIDER_WRITE_TIMEOUT",
        "PROVIDER_POOL_TIMEOUT",
        "PROVIDER_INFERENCE_TIMEOUT",
        "PROVIDER_OVERALL_TIMEOUT",
        "PROVIDER_CONNECTION_ERROR",
        "PROVIDER_RATE_LIMITED",
        "PROVIDER_SERVER_ERROR",
    }
)
TERMINAL_QA_CODES = frozenset(
    {
        "QA_PROVENANCE_CONTRACT_INVALID",
        "QA_SPLIT_INVALID_OUTPUT",
        "QA_SPLIT_MODEL_NOT_CONFIGURED",
        "QA_PROVENANCE_UNKNOWN_CHUNK_INDEX",
        "PROVIDER_UNAUTHORIZED",
        "PROVIDER_REQUEST_ERROR",
        "PROVIDER_OUTPUT_TRUNCATED",
    }
)
_SPLITTABLE_QA_CODES = frozenset(
    {
        "PROVIDER_CONNECTION_TIMEOUT",
        "PROVIDER_WRITE_TIMEOUT",
        "PROVIDER_POOL_TIMEOUT",
        "PROVIDER_INFERENCE_TIMEOUT",
        "PROVIDER_OVERALL_TIMEOUT",
        "PROVIDER_OUTPUT_TRUNCATED",
    }
)
_EMPTY_CONTENT_HASH = hashlib.sha256(b"").hexdigest()


class QaBatchingError(ValueError):
    """A deterministic batching failure that must not be retried as provider I/O."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class QaBatch:
    batch_index: int
    chunks: tuple[DocumentChunk, ...]
    estimated_input_tokens: int
    reserved_output_tokens: int
    input_hash: str
    budget_mode: str = "tokens"
    parent_batch_id: str | None = None
    split_depth: int = 0
    batch_index_path: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not self.batch_index_path:
            object.__setattr__(self, "batch_index_path", (self.batch_index,))

    @property
    def batch_id(self) -> str:
        path = ".".join(str(index) for index in self.batch_index_path)
        return f"{path}:{self.input_hash[:16]}"


@dataclass(frozen=True)
class QaBatchResult:
    """One terminal result for a batch, including any successful split leaves.

    ``raw_output``, ``error`` and ``latency_ms`` intentionally mirror the
    previous private QA service result so existing call-log code can consume
    the new type without losing diagnostics.
    """

    batch: QaBatch
    raw_output: str | None
    error: Exception | None
    latency_ms: int
    retry_count: int = 0
    split_results: tuple["QaBatchResult", ...] = ()

    def leaf_results(self) -> tuple["QaBatchResult", ...]:
        if self.split_results:
            leaves: list[QaBatchResult] = []
            for result in self.split_results:
                leaves.extend(result.leaf_results())
            return tuple(leaves)
        return (self,)


def estimate_qa_prompt_tokens(
    document: Document,
    chunks: list[DocumentChunk],
    token_counter: TokenCounter,
) -> int:
    """Count the exact QA prompt, including the fixed contract and metadata."""

    return estimate_qa_split_prompt_tokens(document, chunks, token_counter)


def _chunk_content_hash(chunk: DocumentChunk) -> str:
    content_hash = getattr(chunk, "content_hash", None)
    if (
        isinstance(content_hash, str)
        and len(content_hash) == 64
        and content_hash != _EMPTY_CONTENT_HASH
    ):
        return content_hash
    content = getattr(chunk, "content", "")
    return hashlib.sha256(str(content).encode("utf-8")).hexdigest()


def qa_batch_input_hash(chunks: Sequence[DocumentChunk]) -> str:
    payload = {
        "promptVersion": QA_SPLIT_PROMPT_VERSION,
        "chunks": [
            {
                "chunkIndex": chunk.chunk_index,
                "contentHash": _chunk_content_hash(chunk),
                "fragmentIndex": getattr(chunk, "_qa_fragment_index", None),
            }
            for chunk in sorted(chunks, key=lambda value: value.chunk_index)
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _make_batch(
    batch_index: int,
    document: Document,
    chunks: Sequence[DocumentChunk],
    token_counter: TokenCounter,
    reserved_output_tokens: int,
    *,
    budget_mode: str = "tokens",
) -> QaBatch:
    ordered_chunks = tuple(sorted(chunks, key=lambda chunk: chunk.chunk_index))
    return QaBatch(
        batch_index=batch_index,
        chunks=ordered_chunks,
        estimated_input_tokens=estimate_qa_prompt_tokens(
            document, list(ordered_chunks), token_counter
        ),
        reserved_output_tokens=reserved_output_tokens,
        input_hash=qa_batch_input_hash(ordered_chunks),
        budget_mode=budget_mode,
    )


def _validate_budget(max_input_tokens: int, reserved_output_tokens: int) -> None:
    if (
        not isinstance(max_input_tokens, int)
        or isinstance(max_input_tokens, bool)
        or max_input_tokens <= 0
    ):
        raise QaBatchingError(
            QA_SPLIT_BATCH_CONFIG_INVALID,
            "QA max_input_tokens 必须为正整数",
        )
    if (
        not isinstance(reserved_output_tokens, int)
        or isinstance(reserved_output_tokens, bool)
        or reserved_output_tokens < 0
    ):
        raise QaBatchingError(
            QA_SPLIT_BATCH_CONFIG_INVALID,
            "QA reserved_output_tokens 必须为非负整数",
        )


def _ensure_single_generation(chunks: Sequence[DocumentChunk]) -> None:
    generations = {
        value
        for chunk in chunks
        if isinstance(
            value := getattr(chunk, "chunker_config_hash", None),
            str,
        )
        and value
    }
    if len(generations) > 1:
        raise QaBatchingError(
            QA_PROVENANCE_CONTRACT_INVALID,
            "QA Batch 不得混入不同 Chunk generation",
        )


def _virtual_chunk(
    chunk: DocumentChunk,
    content: str,
    *,
    fragment_index: int,
    fragment_count: int,
) -> DocumentChunk:
    metadata = dict(getattr(chunk, "chunk_metadata", {}) or {})
    metadata["qaFragmentIndex"] = fragment_index
    metadata["qaFragmentCount"] = fragment_count
    return SimpleNamespace(
        chunk_index=chunk.chunk_index,
        content=content,
        page_no=getattr(chunk, "page_no", None),
        page_start=getattr(chunk, "page_start", None),
        page_end=getattr(chunk, "page_end", None),
        title_path=list(getattr(chunk, "title_path", []) or []),
        content_hash=_chunk_content_hash(chunk),
        chunker_name=getattr(chunk, "chunker_name", "legacy_parser"),
        chunker_config_hash=getattr(chunk, "chunker_config_hash", None),
        chunk_metadata=metadata,
        source_locator=getattr(chunk, "source_locator", None),
        source_locators=getattr(chunk, "source_locators", None),
        _qa_fragment_index=fragment_index,
        _qa_fragment_count=fragment_count,
        _qa_source_content_hash=_chunk_content_hash(chunk),
    )


def _split_legacy_chunk(
    document: Document,
    chunk: DocumentChunk,
    *,
    token_counter: TokenCounter,
    max_input_tokens: int,
    reserved_output_tokens: int,
) -> list[DocumentChunk]:
    empty_fragment = _virtual_chunk(
        chunk,
        "",
        fragment_index=0,
        fragment_count=1,
    )
    fixed_overhead = estimate_qa_prompt_tokens(
        document,
        [empty_fragment],
        token_counter,
    )
    content_limit = max_input_tokens - fixed_overhead
    if content_limit <= 0:
        raise QaBatchingError(
            QA_PROVENANCE_CONTRACT_INVALID,
            "QA Prompt 固定开销已超过输入 token 预算，无法安全拆分 Chunk",
        )

    try:
        parts = token_counter.split_by_token_limit(chunk.content or "", content_limit)
    except (TokenLimitError, TokenizerUnavailableError) as exc:
        raise QaBatchingError(
            QA_PROVENANCE_CONTRACT_INVALID,
            "Legacy Chunk 无法按 token budget 安全拆分",
        ) from exc
    if not parts or "".join(parts) != (chunk.content or ""):
        raise QaBatchingError(
            QA_PROVENANCE_CONTRACT_INVALID,
            "Legacy Chunk token 拆分未完整保留原文",
        )

    fragments = [
        _virtual_chunk(
            chunk,
            part,
            fragment_index=index,
            fragment_count=len(parts),
        )
        for index, part in enumerate(parts)
    ]
    for fragment in fragments:
        if (
            estimate_qa_prompt_tokens(document, [fragment], token_counter)
            > max_input_tokens
        ):
            raise QaBatchingError(
                QA_PROVENANCE_CONTRACT_INVALID,
                "Legacy Chunk token 拆分后仍超过 QA 输入预算",
            )
    return fragments


def group_qa_chunks(
    document: Document,
    chunks: list[DocumentChunk],
    *,
    token_counter: TokenCounter,
    max_input_tokens: int,
    reserved_output_tokens: int,
) -> list[QaBatch]:
    """Greedily pack sorted chunks by the actual QA prompt token count."""

    _validate_budget(max_input_tokens, reserved_output_tokens)
    ordered_chunks = sorted(chunks, key=lambda chunk: chunk.chunk_index)
    _ensure_single_generation(ordered_chunks)

    batches: list[QaBatch] = []
    current: list[DocumentChunk] = []

    def append_current() -> None:
        if current:
            batches.append(
                _make_batch(
                    len(batches),
                    document,
                    current,
                    token_counter,
                    reserved_output_tokens,
                )
            )
            current.clear()

    for chunk in ordered_chunks:
        candidate = [*current, chunk]
        if estimate_qa_prompt_tokens(document, candidate, token_counter) <= max_input_tokens:
            current.append(chunk)
            continue

        append_current()
        if estimate_qa_prompt_tokens(document, [chunk], token_counter) <= max_input_tokens:
            current.append(chunk)
            continue

        if getattr(chunk, "chunker_name", "legacy_parser") == "adaptive_hierarchical":
            raise QaBatchingError(
                QA_PROVENANCE_CONTRACT_INVALID,
                "Adaptive Chunk 超出 QA batch token 预算",
            )

        for fragment in _split_legacy_chunk(
            document,
            chunk,
            token_counter=token_counter,
            max_input_tokens=max_input_tokens,
            reserved_output_tokens=reserved_output_tokens,
        ):
            batches.append(
                _make_batch(
                    len(batches),
                    document,
                    [fragment],
                    token_counter,
                    reserved_output_tokens,
                )
            )

    append_current()
    return batches


def split_qa_batch(batch: QaBatch) -> tuple[QaBatch, QaBatch]:
    """Split a multi-chunk batch into deterministic halves for later retries."""

    if len(batch.chunks) < 2:
        raise QaBatchingError(
            QA_PROVENANCE_CONTRACT_INVALID,
            "单 Chunk QA Batch 不能继续二分",
        )
    middle = len(batch.chunks) // 2
    left_chunks = batch.chunks[:middle]
    right_chunks = batch.chunks[middle:]

    def child(chunks: tuple[DocumentChunk, ...], child_index: int) -> QaBatch:
        total_content = sum(len(chunk.content or "") for chunk in batch.chunks)
        child_content = sum(len(chunk.content or "") for chunk in chunks)
        estimated = max(
            1,
            round(batch.estimated_input_tokens * child_content / max(1, total_content)),
        )
        return QaBatch(
            # Keep the root index so final output can be ordered with the
            # original batch. The binary child position lives in the path.
            batch_index=batch.batch_index,
            chunks=chunks,
            estimated_input_tokens=estimated,
            reserved_output_tokens=batch.reserved_output_tokens,
            input_hash=qa_batch_input_hash(chunks),
            budget_mode=batch.budget_mode,
            parent_batch_id=batch.batch_id,
            split_depth=batch.split_depth + 1,
            batch_index_path=batch.batch_index_path + (child_index,),
        )

    return (
        child(left_chunks, 0),
        child(right_chunks, 1),
    )


def execute_qa_batch_with_retry(
    adapter,
    batch: QaBatch,
    *,
    max_retries: int,
    max_split_depth: int,
) -> QaBatchResult:
    """Execute one QA batch with bounded retry and timeout-size reduction.

    The caller supplies an adapter with either ``generate_qa_batch(batch)`` or
    the legacy ``generate_qa_pairs(batch)`` method.  The latter keeps focused
    tests and older service call sites compatible; production wraps its
    provider adapter to turn the batch into a prompt.
    """

    retries = _non_negative_limit(max_retries)
    split_depth_limit = _non_negative_limit(max_split_depth)
    attempt = 0
    total_latency_ms = 0

    while True:
        started_at = time.perf_counter()
        try:
            raw_output = _generate_qa_batch(adapter, batch)
        except Exception as exc:
            total_latency_ms += max(1, int((time.perf_counter() - started_at) * 1000))
            code = _error_code(exc)
            if _is_retryable_qa_error(exc, code) and attempt < retries:
                metrics.observe_qa_split_retry(
                    provider_type=getattr(adapter, "provider_type", None),
                    error_code=code,
                )
                time.sleep(_retry_delay_seconds(exc, attempt))
                attempt += 1
                continue

            result = QaBatchResult(
                batch=batch,
                raw_output=None,
                error=exc,
                latency_ms=total_latency_ms,
                retry_count=attempt,
            )
            if (
                code in _SPLITTABLE_QA_CODES
                and len(batch.chunks) > 1
                and batch.split_depth < split_depth_limit
            ):
                metrics.observe_qa_split_batch_split(
                    provider_type=getattr(adapter, "provider_type", None),
                    reason=_split_reason(code),
                )
                left, right = split_qa_batch(batch)
                return QaBatchResult(
                    batch=batch,
                    raw_output=None,
                    error=exc,
                    latency_ms=total_latency_ms,
                    retry_count=attempt,
                    split_results=(
                        execute_qa_batch_with_retry(
                            adapter,
                            left,
                            max_retries=retries,
                            max_split_depth=split_depth_limit,
                        ),
                        execute_qa_batch_with_retry(
                            adapter,
                            right,
                            max_retries=retries,
                            max_split_depth=split_depth_limit,
                        ),
                    ),
                )
            return result
        else:
            total_latency_ms += max(1, int((time.perf_counter() - started_at) * 1000))
            return QaBatchResult(
                batch=batch,
                raw_output=raw_output,
                error=None,
                latency_ms=total_latency_ms,
                retry_count=attempt,
            )


def _non_negative_limit(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        return 0
    return max(0, value)


def _generate_qa_batch(adapter, batch: QaBatch) -> str:
    generate_batch = getattr(adapter, "generate_qa_batch", None)
    if callable(generate_batch):
        return generate_batch(batch)
    return adapter.generate_qa_pairs(batch)


def _error_code(error: Exception) -> str | None:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) else None


def _split_reason(code: str | None) -> str:
    if code == "PROVIDER_OUTPUT_TRUNCATED":
        return "output_truncated"
    if code in _SPLITTABLE_QA_CODES:
        return "timeout"
    return "other"


def _is_retryable_qa_error(error: Exception, code: str | None) -> bool:
    if code in TERMINAL_QA_CODES or code not in RETRYABLE_QA_CODES:
        return False
    if isinstance(error, ProviderError):
        return error.retryable
    return bool(getattr(error, "retryable", False))


def _retry_delay_seconds(error: Exception, attempt: int) -> float:
    """Return bounded delay for QA batch retry attempts.

    Rate-limit hints may be surfaced by a provider adapter as either a numeric
    ``retry_after_seconds``/``retry_after`` attribute or a response-header
    mapping. Invalid or unavailable hints fall back to the normal schedule.
    """

    default_delay = min(8.0, 0.5 * (2**max(0, attempt)))
    if _error_code(error) != "PROVIDER_RATE_LIMITED":
        return default_delay
    retry_after = _retry_after_seconds(error)
    return min(30.0, retry_after) if retry_after is not None else default_delay


def _retry_after_seconds(error: Exception) -> float | None:
    candidates = [
        getattr(error, "retry_after_seconds", None),
        getattr(error, "retry_after", None),
    ]
    context = getattr(error, "context", None)
    if isinstance(context, dict):
        candidates.extend(
            (
                context.get("retry_after_seconds"),
                context.get("retryAfter"),
                context.get("retry-after"),
            )
        )
        headers = context.get("headers")
        if isinstance(headers, dict):
            candidates.extend((headers.get("Retry-After"), headers.get("retry-after")))
    headers = getattr(error, "headers", None)
    if isinstance(headers, dict):
        candidates.extend((headers.get("Retry-After"), headers.get("retry-after")))

    for candidate in candidates:
        parsed = _parse_retry_after(candidate)
        if parsed is not None:
            return parsed
    return None


def _parse_retry_after(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if value > 0 else None
    if not isinstance(value, str):
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        seconds = (retry_at - datetime.now(UTC)).total_seconds()
    return seconds if seconds > 0 else None
