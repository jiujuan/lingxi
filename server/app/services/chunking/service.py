"""Deterministic orchestration for adaptive hierarchical chunking."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from server.app.services.chunking.contracts import (
    AtomicBlock,
    BlockType,
    ChunkingResult,
    ChunkingStats,
    ChunkingWarning,
    ChunkLevel,
    NormalizedChunk,
    to_json_value,
)
from server.app.services.chunking.identity import (
    assign_call_source_identity,
    source_identity,
)
from server.app.services.chunking.merge import (
    MergedBlock,
    MergeResult,
    merge_small_blocks,
)
from server.app.services.chunking.overlap import apply_prose_overlap
from server.app.services.chunking.normalization import (
    NORMALIZATION_METADATA_KEY,
    normalize_text,
    normalize_text_with_map,
)
from server.app.services.chunking.policy import ChunkPolicy
from server.app.services.chunking.recursive_splitter import split_oversized_prose
from server.app.services.chunking.tokenizer import TokenCounter, require_token_counter
from server.app.services.chunking.versions import TYPE_HANDLER_VERSIONS
from server.app.services.chunking.type_handlers import (
    TYPE_HANDLER_REGISTRY,
    TypeHandlerContext,
    handle_typed_block,
)

_UNKNOWN_BLOCK_TYPE_NORMALIZED = "UNKNOWN_BLOCK_TYPE_NORMALIZED"
_EMPTY_ATOMIC_BLOCK_SKIPPED = "EMPTY_ATOMIC_BLOCK_SKIPPED"
_PARENT_SEPARATOR = "\n\n"


class ChunkingFeatureUnsupportedError(ValueError):
    """Non-retryable structured rejection for declared but inactive features."""

    code = "CHUNK_FEATURE_UNSUPPORTED"
    retryable = False

    def __init__(self, feature: str) -> None:
        self.feature = feature
        super().__init__(f"{self.code}: unsupported chunking feature: {feature}")


@dataclass(frozen=True)
class _SectionKey:
    source_identity: str
    title_path: tuple[str, ...]
    parent_structural_id: str | None


@dataclass(frozen=True)
class _ChildDraft:
    content: str
    unique_content: str
    block_type: BlockType
    title_path: tuple[str, ...]
    token_count: int
    page_start: int | None
    page_end: int | None
    source_locators: tuple[Mapping[str, Any], ...]
    atomic_block_indexes: tuple[int, ...]
    overlap_prefix_tokens: int
    metadata: Mapping[str, Any]
    section_key: _SectionKey


@dataclass(frozen=True)
class _ParentSegment:
    child_indexes: tuple[int, ...]
    section_key: _SectionKey
    section_segment_index: int


class _OperationTokenCounter:
    """Bound repeated tokenizer work to one chunking operation.

    Recursive splitting, overlap construction, parent packing, and final row
    construction intentionally re-check token budgets.  They frequently ask
    about the same immutable text, so memoizing exact inputs preserves the
    tokenizer contract while avoiding repeated BPE encodes.
    """

    _lingxi_validated_token_counter = True

    def __init__(self, delegate: TokenCounter) -> None:
        self._delegate = delegate
        self.name = delegate.name
        self.version = delegate.version
        self._counts: dict[str, int] = {}
        self._splits: dict[tuple[str, int], tuple[str, ...]] = {}

    def count(self, text: str) -> int:
        if text not in self._counts:
            self._counts[text] = self._delegate.count(text)
        return self._counts[text]

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        key = (text, limit)
        if key not in self._splits:
            self._splits[key] = tuple(
                self._delegate.split_by_token_limit(text, limit)
            )
        return list(self._splits[key])


def _content_hash(content: str) -> str:
    """Hash content emitted by this service after its normalization boundary."""

    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _section_key(block: AtomicBlock) -> _SectionKey:
    identity = source_identity(block)
    if identity is None:
        raise ValueError("normalized block requires a source identity")
    return _SectionKey(
        source_identity=identity,
        title_path=block.title_path,
        parent_structural_id=block.parent_structural_id,
    )


def _chunker_metadata(
    policy: ChunkPolicy,
    counter: TokenCounter,
    document_title: str,
) -> dict[str, Any]:
    return {
        "name": policy.name,
        "version": policy.version,
        "configHash": policy.config_hash,
        "tokenizerName": counter.name,
        "tokenizerVersion": counter.version,
        "documentTitle": document_title,
    }


def _with_chunker_metadata(
    metadata: Mapping[str, Any],
    *,
    policy: ChunkPolicy,
    counter: TokenCounter,
    document_title: str,
) -> dict[str, Any]:
    output = to_json_value(metadata)
    output["chunker"] = _chunker_metadata(policy, counter, document_title)
    return output


def _normalize_blocks(
    blocks: Sequence[AtomicBlock],
    *,
    document_title: str,
) -> tuple[tuple[AtomicBlock, ...], tuple[ChunkingWarning, ...], int]:
    ordered = sorted(blocks, key=lambda block: block.index)
    indexes = [block.index for block in ordered]
    if any(
        not isinstance(index, int) or isinstance(index, bool) or index < 0
        for index in indexes
    ):
        raise ValueError("AtomicBlock.index must be a non-negative integer")
    if len(indexes) != len(set(indexes)):
        raise ValueError("duplicate AtomicBlock.index values are not allowed")
    ordered = list(
        assign_call_source_identity(ordered, document_title=document_title)
    )

    normalized: list[AtomicBlock] = []
    warnings: list[ChunkingWarning] = []
    skipped = 0
    for block in ordered:
        content, normalization = normalize_text_with_map(block.content)
        if not content:
            skipped += 1
            warnings.append(
                ChunkingWarning(
                    code=_EMPTY_ATOMIC_BLOCK_SKIPPED,
                    message=(
                        "Atomic block became empty after deterministic "
                        "normalization"
                    ),
                    metadata={"atomicBlockIndex": block.index},
                )
            )
            continue

        block_type = block.block_type
        metadata = to_json_value(block.metadata)
        metadata[NORMALIZATION_METADATA_KEY] = normalization
        if block_type is BlockType.UNKNOWN:
            block_type = BlockType.TEXT
            metadata["originalBlockType"] = BlockType.UNKNOWN.value
            warnings.append(
                ChunkingWarning(
                    code=_UNKNOWN_BLOCK_TYPE_NORMALIZED,
                    message=(
                        "Unknown atomic block type was conservatively handled "
                        "as text"
                    ),
                    metadata={"atomicBlockIndex": block.index},
                )
            )
        normalized.append(
            replace(
                block,
                content=content,
                block_type=block_type,
                title_path=tuple(
                    normalize_text(part) for part in block.title_path
                ),
                metadata=metadata,
            )
        )
    return tuple(normalized), tuple(warnings), skipped


def _single_merged_block(
    block: AtomicBlock, counter: TokenCounter
) -> MergedBlock:
    return MergedBlock(
        content=block.content,
        block_type=block.block_type,
        title_path=block.title_path,
        token_count=counter.count(block.content),
        page_start=block.page_no,
        page_end=block.page_no,
        source_locators=(block.source_locator,),
        atomic_block_indexes=(block.index,),
        atomic_blocks=(block,),
    )


def _merge_for_orchestration(
    blocks: Sequence[AtomicBlock],
    policy: ChunkPolicy,
    counter: TokenCounter,
) -> MergeResult:
    """Merge only ordinary prose runs; every registered typed block is isolated."""

    output: list[MergedBlock] = []
    warnings: list[ChunkingWarning] = []
    merge_count = 0
    prose_run: list[AtomicBlock] = []

    def flush_prose() -> None:
        nonlocal merge_count
        if not prose_run:
            return
        result = merge_small_blocks(tuple(prose_run), policy, counter)
        output.extend(result.blocks)
        warnings.extend(result.warnings)
        merge_count += result.merge_count
        prose_run.clear()

    for block in blocks:
        if block.block_type in TYPE_HANDLER_REGISTRY:
            flush_prose()
            output.append(_single_merged_block(block, counter))
        else:
            prose_run.append(block)
    flush_prose()
    return MergeResult(tuple(output), tuple(warnings), merge_count)


def _original_type_metadata(blocks: Sequence[AtomicBlock]) -> dict[str, Any]:
    original_types = {
        value
        for block in blocks
        if isinstance((value := block.metadata.get("originalBlockType")), str)
    }
    if not original_types:
        return {}
    if len(original_types) == 1:
        return {"originalBlockType": next(iter(original_types))}
    return {"originalBlockTypes": sorted(original_types)}


def _context_for_atomic(
    block: AtomicBlock,
    *,
    ordered: Sequence[AtomicBlock],
    position_by_index: Mapping[int, int],
) -> TypeHandlerContext:
    position = position_by_index[block.index]
    identity = source_identity(block)
    if identity is None:
        raise ValueError("normalized block requires a source identity")

    previous = ordered[position - 1] if position > 0 else None
    following = ordered[position + 1] if position + 1 < len(ordered) else None
    if previous is not None and source_identity(previous) != identity:
        previous = None
    if following is not None and source_identity(following) != identity:
        following = None

    return TypeHandlerContext(
        previous=previous,
        following=following,
        source_identity=identity,
        current_position=position,
        previous_position=position - 1 if previous is not None else None,
        following_position=position + 1 if following is not None else None,
    )


def _draft_from_typed(
    draft: Any,
    *,
    origin: AtomicBlock,
    counter: TokenCounter,
) -> _ChildDraft:
    content = normalize_text(draft.content)
    unique_content = normalize_text(draft.unique_content)
    return _ChildDraft(
        content=content,
        unique_content=unique_content,
        block_type=draft.block_type,
        title_path=draft.title_path,
        token_count=counter.count(content),
        page_start=draft.page_start,
        page_end=draft.page_end,
        source_locators=draft.source_locators,
        atomic_block_indexes=draft.atomic_block_indexes,
        overlap_prefix_tokens=draft.overlap_prefix_tokens,
        metadata=draft.metadata,
        section_key=_section_key(origin),
    )


def _drafts_from_prose(
    block: MergedBlock,
    *,
    policy: ChunkPolicy,
    counter: TokenCounter,
) -> tuple[tuple[_ChildDraft, ...], int, int]:
    split_result = split_oversized_prose(block, policy, counter)
    overlap_result = apply_prose_overlap(split_result, policy, counter)
    original_type = _original_type_metadata(block.atomic_blocks)
    drafts: list[_ChildDraft] = []
    for candidate in overlap_result.blocks:
        metadata = to_json_value(candidate.metadata)
        metadata.update(original_type)
        metadata["split"] = {
            "reason": candidate.split_reason.value,
            "relativeCharStart": candidate.relative_char_start,
            "relativeCharEnd": candidate.relative_char_end,
        }
        # Split and overlap operate only on already-normalized atomic content.
        # Their only introduced separator is LF, so re-running full Unicode
        # normalization here is redundant and would not change output.
        content = candidate.content
        unique_content = candidate.unique_content
        drafts.append(
            _ChildDraft(
                content=content,
                unique_content=unique_content,
                block_type=candidate.block_type,
                title_path=candidate.title_path,
                token_count=counter.count(content),
                page_start=candidate.page_start,
                page_end=candidate.page_end,
                source_locators=candidate.source_locators,
                atomic_block_indexes=candidate.atomic_block_indexes,
                overlap_prefix_tokens=candidate.overlap_prefix_tokens,
                metadata=metadata,
                section_key=_section_key(block.atomic_blocks[0]),
            )
        )
    return (
        tuple(drafts),
        split_result.split_count,
        split_result.oversized_count,
    )


def _child_drafts(
    merged_blocks: Sequence[MergedBlock],
    *,
    ordered_blocks: Sequence[AtomicBlock],
    policy: ChunkPolicy,
    counter: TokenCounter,
) -> tuple[
    tuple[_ChildDraft, ...],
    tuple[ChunkingWarning, ...],
    int,
    int,
    int,
]:
    position_by_index = {
        block.index: position for position, block in enumerate(ordered_blocks)
    }
    drafts: list[_ChildDraft] = []
    warnings: list[ChunkingWarning] = []
    skipped = 0
    split_count = 0
    oversized_count = 0

    for merged in merged_blocks:
        is_single_typed_atomic = (
            len(merged.atomic_blocks) == 1
            and merged.atomic_blocks[0].block_type in TYPE_HANDLER_REGISTRY
        )
        if is_single_typed_atomic:
            origin = merged.atomic_blocks[0]
            handler_result = handle_typed_block(
                origin,
                policy,
                counter,
                context=_context_for_atomic(
                    origin,
                    ordered=ordered_blocks,
                    position_by_index=position_by_index,
                ),
            )
            warnings.extend(handler_result.warnings)
            if not handler_result.drafts:
                skipped += 1
            drafts.extend(
                _draft_from_typed(draft, origin=origin, counter=counter)
                for draft in handler_result.drafts
            )
            continue

        prose_drafts, prose_splits, prose_oversized = _drafts_from_prose(
            merged,
            policy=policy,
            counter=counter,
        )
        drafts.extend(prose_drafts)
        split_count += prose_splits
        oversized_count += prose_oversized

    if any(draft.token_count > policy.max_tokens for draft in drafts):
        raise ValueError("ChunkingService emitted a Child over max_tokens")
    return (
        tuple(drafts),
        tuple(warnings),
        skipped,
        split_count,
        oversized_count,
    )


def _parent_content(
    child_indexes: Sequence[int], drafts: Sequence[_ChildDraft]
) -> str:
    content = ""
    has_content = False
    for index in child_indexes:
        draft = drafts[index]
        if not draft.unique_content:
            continue
        separator = _PARENT_SEPARATOR if has_content else ""
        list_metadata = draft.metadata.get("list")
        if isinstance(list_metadata, Mapping):
            joiner = list_metadata.get("uniqueJoinerBefore")
            if (
                has_content
                and list_metadata.get("uniqueContinuation") is True
                and isinstance(joiner, str)
                and joiner in {"", " "}
            ):
                separator = joiner
        content += separator + draft.unique_content
        has_content = True
    return content


def _segment_section_run(
    child_indexes: Sequence[int],
    drafts: Sequence[_ChildDraft],
    *,
    policy: ChunkPolicy,
    counter: TokenCounter,
) -> tuple[tuple[int, ...], ...]:
    """Find bounded Parent segments with exponential/binary Child-boundary search."""

    indexes = tuple(child_indexes)
    cache: dict[tuple[int, int], int] = {}

    def token_count(start: int, end: int) -> int:
        key = (start, end)
        if key not in cache:
            cache[key] = counter.count(_parent_content(indexes[start:end], drafts))
        return cache[key]

    segments: list[tuple[int, ...]] = []
    start = 0
    while start < len(indexes):
        if token_count(start, start + 1) > policy.parent_max_tokens:
            raise ValueError("Parent segment exceeds parent_max_tokens")

        last_good = start + 1
        step = 2
        first_bad: int | None = None
        while start + step <= len(indexes):
            candidate_end = start + step
            if token_count(start, candidate_end) <= policy.parent_max_tokens:
                last_good = candidate_end
                step *= 2
            else:
                first_bad = candidate_end
                break

        if first_bad is None:
            if last_good == len(indexes):
                end = last_good
            else:
                tail_end = len(indexes)
                if token_count(start, tail_end) <= policy.parent_max_tokens:
                    end = tail_end
                else:
                    first_bad = tail_end
        if first_bad is not None:
            low = last_good + 1
            high = first_bad - 1
            end = last_good
            while low <= high:
                middle = (low + high) // 2
                if token_count(start, middle) <= policy.parent_max_tokens:
                    end = middle
                    low = middle + 1
                else:
                    high = middle - 1

        if token_count(start, end) > policy.parent_max_tokens:
            raise ValueError("Parent segment exceeds parent_max_tokens")
        segments.append(indexes[start:end])
        start = end
    return tuple(segments)


def _segment_parents(
    drafts: Sequence[_ChildDraft],
    *,
    policy: ChunkPolicy,
    counter: TokenCounter,
) -> tuple[_ParentSegment, ...]:
    segments: list[_ParentSegment] = []
    section_segment_counts: dict[_SectionKey, int] = {}
    run_start = 0
    while run_start < len(drafts):
        key = drafts[run_start].section_key
        run_end = run_start + 1
        while run_end < len(drafts) and drafts[run_end].section_key == key:
            run_end += 1
        for child_indexes in _segment_section_run(
            tuple(range(run_start, run_end)),
            drafts,
            policy=policy,
            counter=counter,
        ):
            section_index = section_segment_counts.get(key, 0)
            segments.append(_ParentSegment(child_indexes, key, section_index))
            section_segment_counts[key] = section_index + 1
        run_start = run_end
    return tuple(segments)


def _deduplicated_locators(
    child_indexes: Sequence[int], drafts: Sequence[_ChildDraft]
) -> tuple[Mapping[str, Any], ...]:
    output: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for child_index in child_indexes:
        for locator in drafts[child_index].source_locators:
            key = json.dumps(
                to_json_value(locator),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            if key not in seen:
                seen.add(key)
                output.append(locator)
    return tuple(output)


def _deduplicated_indexes(
    child_indexes: Sequence[int], drafts: Sequence[_ChildDraft]
) -> tuple[int, ...]:
    output: list[int] = []
    seen: set[int] = set()
    for child_index in child_indexes:
        for atomic_index in drafts[child_index].atomic_block_indexes:
            if atomic_index not in seen:
                seen.add(atomic_index)
                output.append(atomic_index)
    return tuple(output)


def _page_range(
    child_indexes: Sequence[int], drafts: Sequence[_ChildDraft]
) -> tuple[int | None, int | None]:
    pages = [
        page
        for child_index in child_indexes
        for page in (drafts[child_index].page_start, drafts[child_index].page_end)
        if page is not None
    ]
    return (min(pages), max(pages)) if pages else (None, None)


def _parent_block_type(
    child_indexes: Sequence[int], drafts: Sequence[_ChildDraft]
) -> BlockType:
    block_types = {drafts[index].block_type for index in child_indexes}
    return next(iter(block_types)) if len(block_types) == 1 else BlockType.TEXT


class ChunkingService:
    """Pure normalize/merge/split/overlap/parent orchestration service."""

    def __init__(self, token_counter: TokenCounter) -> None:
        self._token_counter = require_token_counter(token_counter)

    def chunk(
        self,
        blocks: Sequence[AtomicBlock],
        policy: ChunkPolicy,
        *,
        document_title: str,
    ) -> ChunkingResult:
        if not isinstance(policy, ChunkPolicy):
            raise ValueError("policy must be a ChunkPolicy")
        if policy.semantic_split_enabled:
            raise ChunkingFeatureUnsupportedError("semantic_split_enabled")
        if not isinstance(document_title, str) or not document_title.strip():
            raise ValueError("document_title must be a non-empty string")
        if isinstance(blocks, (str, bytes)):
            raise ValueError("blocks must be a sequence of AtomicBlock values")
        input_blocks = tuple(blocks)
        if any(not isinstance(block, AtomicBlock) for block in input_blocks):
            raise ValueError("blocks must contain only AtomicBlock values")

        counter = _OperationTokenCounter(self._token_counter)
        if (
            policy.tokenizer_name != counter.name
            or policy.tokenizer_version != counter.version
        ):
            raise ValueError(
                "policy tokenizer name/version must match the ChunkingService tokenizer"
            )
        if dict(policy.type_handler_versions) != dict(TYPE_HANDLER_VERSIONS):
            raise ValueError(
                "policy type handler versions must exactly match registered handlers"
            )
        normalized_title = normalize_text(document_title)
        normalized, normalization_warnings, normalization_skips = _normalize_blocks(
            input_blocks,
            document_title=normalized_title,
        )
        if not normalized:
            return ChunkingResult(
                parents=(),
                children=(),
                stats=ChunkingStats(
                    input_block_count=len(input_blocks),
                    skipped_block_count=normalization_skips,
                ),
                warnings=normalization_warnings,
            )

        merge_result = _merge_for_orchestration(normalized, policy, counter)
        (
            drafts,
            handler_warnings,
            handler_skips,
            split_count,
            oversized_count,
        ) = _child_drafts(
            merge_result.blocks,
            ordered_blocks=normalized,
            policy=policy,
            counter=counter,
        )
        segments = _segment_parents(drafts, policy=policy, counter=counter)

        parent_id_by_child: dict[int, str] = {}
        for parent_index, segment in enumerate(segments):
            parent_local_id = f"parent-{parent_index:06d}"
            for child_index in segment.child_indexes:
                parent_id_by_child[child_index] = parent_local_id

        children: list[NormalizedChunk] = []
        for child_index, draft in enumerate(drafts):
            metadata = _with_chunker_metadata(
                draft.metadata,
                policy=policy,
                counter=counter,
                document_title=normalized_title,
            )
            children.append(
                NormalizedChunk(
                    local_id=f"child-{child_index:06d}",
                    level=ChunkLevel.CHILD,
                    parent_local_id=parent_id_by_child[child_index],
                    chunk_index=child_index,
                    block_type=draft.block_type,
                    content=draft.content,
                    title_path=draft.title_path,
                    token_count=draft.token_count,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    source_locators=draft.source_locators,
                    atomic_block_indexes=draft.atomic_block_indexes,
                    overlap_prefix_tokens=draft.overlap_prefix_tokens,
                    content_hash=_content_hash(draft.content),
                    metadata=metadata,
                )
            )

        parents: list[NormalizedChunk] = []
        for parent_index, segment in enumerate(segments):
            child_indexes = segment.child_indexes
            content = _parent_content(child_indexes, drafts)
            page_start, page_end = _page_range(child_indexes, drafts)
            child_local_ids = tuple(children[index].local_id for index in child_indexes)
            metadata = _with_chunker_metadata(
                {
                    "childLocalIds": child_local_ids,
                    "childIndexes": child_indexes,
                    "sectionSegmentIndex": segment.section_segment_index,
                    "parentStructuralId": segment.section_key.parent_structural_id,
                },
                policy=policy,
                counter=counter,
                document_title=normalized_title,
            )
            parents.append(
                NormalizedChunk(
                    local_id=f"parent-{parent_index:06d}",
                    level=ChunkLevel.PARENT,
                    parent_local_id=None,
                    chunk_index=parent_index,
                    block_type=_parent_block_type(child_indexes, drafts),
                    content=content,
                    title_path=segment.section_key.title_path,
                    token_count=counter.count(content),
                    page_start=page_start,
                    page_end=page_end,
                    source_locators=_deduplicated_locators(child_indexes, drafts),
                    atomic_block_indexes=_deduplicated_indexes(child_indexes, drafts),
                    overlap_prefix_tokens=0,
                    content_hash=_content_hash(content),
                    metadata=metadata,
                )
            )

        warnings = (
            normalization_warnings
            + merge_result.warnings
            + handler_warnings
        )
        return ChunkingResult(
            parents=tuple(parents),
            children=tuple(children),
            stats=ChunkingStats(
                input_block_count=len(input_blocks),
                parent_count=len(parents),
                child_count=len(children),
                skipped_block_count=normalization_skips + handler_skips,
                total_token_count=sum(child.token_count for child in children),
                merge_count=merge_result.merge_count,
                split_count=split_count,
                oversized_count=oversized_count,
            ),
            warnings=warnings,
        )


__all__ = ["ChunkingFeatureUnsupportedError", "ChunkingService"]
