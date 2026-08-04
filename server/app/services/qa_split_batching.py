"""Deterministic token-budget batching for QA split prompts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import SimpleNamespace
from typing import Sequence

from server.app.models.document import Document
from server.app.models.qa_pair import DocumentChunk
from server.app.services.chunking import TokenCounter, TokenLimitError, TokenizerUnavailableError
from server.app.services.qa_prompt_builder import (
    QA_SPLIT_PROMPT_VERSION,
    estimate_qa_split_prompt_tokens,
)

QA_SPLIT_BATCH_CONFIG_INVALID = "QA_SPLIT_BATCH_CONFIG_INVALID"
QA_PROVENANCE_CONTRACT_INVALID = "QA_PROVENANCE_CONTRACT_INVALID"
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

    def child(chunks: tuple[DocumentChunk, ...], index: int) -> QaBatch:
        total_content = sum(len(chunk.content or "") for chunk in batch.chunks)
        child_content = sum(len(chunk.content or "") for chunk in chunks)
        estimated = max(
            1,
            round(batch.estimated_input_tokens * child_content / max(1, total_content)),
        )
        return QaBatch(
            batch_index=index,
            chunks=chunks,
            estimated_input_tokens=estimated,
            reserved_output_tokens=batch.reserved_output_tokens,
            input_hash=qa_batch_input_hash(chunks),
            budget_mode=batch.budget_mode,
        )

    return (
        child(left_chunks, batch.batch_index * 2),
        child(right_chunks, batch.batch_index * 2 + 1),
    )
