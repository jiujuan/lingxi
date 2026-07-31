"""Safe-boundary grouping and deterministic merging for small atomic blocks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from server.app.services.chunking.contracts import (
    AtomicBlock,
    BlockType,
    ChunkingWarning,
    _freeze_json_mapping,
)
from server.app.services.chunking.policy import ChunkPolicy
from server.app.services.chunking.tokenizer import TokenCounter, require_token_counter

_MERGEABLE_PROSE_TYPES = frozenset(
    {BlockType.TEXT, BlockType.LIST, BlockType.QUOTE}
)
_STRONG_BOUNDARY_TYPES = frozenset(
    {BlockType.TABLE, BlockType.CODE, BlockType.IMAGE, BlockType.FORMULA}
)
_TINY_CHUNK_UNMERGEABLE = "TINY_CHUNK_UNMERGEABLE"


@dataclass(frozen=True)
class MergedBlock:
    """A merge-stage chunk candidate with complete atomic provenance."""

    content: str
    block_type: BlockType
    title_path: tuple[str, ...]
    token_count: int
    page_start: int | None
    page_end: int | None
    source_locators: tuple[Mapping[str, Any], ...]
    atomic_block_indexes: tuple[int, ...]
    atomic_blocks: tuple[AtomicBlock, ...]

    def __post_init__(self) -> None:
        title_path = tuple(self.title_path)
        atomic_blocks = tuple(self.atomic_blocks)
        atomic_block_indexes = tuple(self.atomic_block_indexes)
        raw_source_locators = tuple(self.source_locators)
        source_locators = tuple(
            _freeze_json_mapping(
                locator,
                field_name="MergedBlock source locator",
            )
            for locator in raw_source_locators
        )

        if not atomic_blocks or not (
            len(source_locators)
            == len(atomic_block_indexes)
            == len(atomic_blocks)
        ):
            raise ValueError(
                "MergedBlock provenance sequences must be non-empty and aligned"
            )
        if atomic_block_indexes != tuple(
            block.index for block in atomic_blocks
        ):
            raise ValueError(
                "MergedBlock provenance indexes must match atomic blocks"
            )
        if source_locators != tuple(
            block.source_locator for block in atomic_blocks
        ):
            raise ValueError(
                "MergedBlock provenance locators must match atomic blocks"
            )
        if any(block.title_path != title_path for block in atomic_blocks):
            raise ValueError(
                "MergedBlock provenance title paths must match the merged block"
            )

        pages = [
            block.page_no for block in atomic_blocks if block.page_no is not None
        ]
        expected_page_start = min(pages) if pages else None
        expected_page_end = max(pages) if pages else None
        if (self.page_start, self.page_end) != (
            expected_page_start,
            expected_page_end,
        ):
            raise ValueError(
                "MergedBlock provenance page range must match atomic blocks"
            )

        object.__setattr__(self, "block_type", BlockType(self.block_type))
        object.__setattr__(self, "title_path", title_path)
        object.__setattr__(self, "source_locators", source_locators)
        object.__setattr__(
            self,
            "atomic_block_indexes",
            atomic_block_indexes,
        )
        object.__setattr__(self, "atomic_blocks", atomic_blocks)


@dataclass(frozen=True)
class MergeResult:
    """Outputs and warnings produced by the small-block merge stage."""

    blocks: tuple[MergedBlock, ...]
    warnings: tuple[ChunkingWarning, ...]
    merge_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "blocks", tuple(self.blocks))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        if not isinstance(self.merge_count, int) or isinstance(
            self.merge_count, bool
        ) or self.merge_count < 0:
            raise ValueError("MergeResult merge_count must be a non-negative integer")


def _is_hard_boundary(block: AtomicBlock) -> bool:
    return block.metadata.get("hard_boundary") is True


def _is_mergeable_prose(block: AtomicBlock) -> bool:
    return block.block_type in _MERGEABLE_PROSE_TYPES


def _can_share_safe_window(
    previous: AtomicBlock,
    current: AtomicBlock,
    policy: ChunkPolicy,
) -> bool:
    if not _is_mergeable_prose(previous) or not _is_mergeable_prose(current):
        return False
    if previous.block_type in _STRONG_BOUNDARY_TYPES:
        return False
    if current.block_type in _STRONG_BOUNDARY_TYPES:
        return False
    if _is_hard_boundary(previous) or _is_hard_boundary(current):
        return False
    if previous.title_path != current.title_path:
        return False
    if previous.parent_structural_id != current.parent_structural_id:
        return False
    if (
        not policy.allow_cross_page_merge
        and previous.page_no != current.page_no
    ):
        return False
    return True


def group_by_safe_boundary(
    blocks: Sequence[AtomicBlock],
    policy: ChunkPolicy,
) -> tuple[tuple[AtomicBlock, ...], ...]:
    """Group stably ordered blocks without crossing a structural boundary.

    Strongly typed and non-prose blocks are isolated because their dedicated
    handlers, rather than the generic prose merger, own their formatting.
    """

    ordered = sorted(blocks, key=lambda block: block.index)
    groups: list[tuple[AtomicBlock, ...]] = []
    current_group: list[AtomicBlock] = []

    for current in ordered:
        if not current_group:
            current_group.append(current)
        elif _can_share_safe_window(current_group[-1], current, policy):
            current_group.append(current)
        else:
            groups.append(tuple(current_group))
            current_group = [current]

        if _is_hard_boundary(current) or not _is_mergeable_prose(current):
            groups.append(tuple(current_group))
            current_group = []

    if current_group:
        groups.append(tuple(current_group))
    return tuple(groups)


def _join_separator(previous: AtomicBlock, current: AtomicBlock) -> str:
    if previous.block_type is BlockType.LIST and current.block_type is BlockType.LIST:
        return "\n"
    return "\n\n"


def _joined_content(blocks: Sequence[AtomicBlock]) -> str:
    if not blocks:
        return ""
    parts = [blocks[0].content]
    for previous, current in zip(blocks, blocks[1:], strict=False):
        parts.append(_join_separator(previous, current))
        parts.append(current.content)
    return "".join(parts)


def _merged_block_type(blocks: Sequence[AtomicBlock]) -> BlockType:
    block_types = {block.block_type for block in blocks}
    if len(block_types) == 1:
        return blocks[0].block_type
    return BlockType.TEXT


def _build_merged_block(
    blocks: Sequence[AtomicBlock],
    token_counter: TokenCounter,
) -> MergedBlock:
    atomic_blocks = tuple(blocks)
    content = _joined_content(atomic_blocks)
    pages = [block.page_no for block in atomic_blocks if block.page_no is not None]
    return MergedBlock(
        content=content,
        block_type=_merged_block_type(atomic_blocks),
        title_path=atomic_blocks[0].title_path,
        token_count=token_counter.count(content),
        page_start=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
        source_locators=tuple(block.source_locator for block in atomic_blocks),
        atomic_block_indexes=tuple(block.index for block in atomic_blocks),
        atomic_blocks=atomic_blocks,
    )


def _combine(
    left: MergedBlock,
    right: MergedBlock,
    token_counter: TokenCounter,
) -> MergedBlock:
    return _build_merged_block(left.atomic_blocks + right.atomic_blocks, token_counter)


def _can_merge_forward(
    buffer: MergedBlock,
    merged: MergedBlock,
    policy: ChunkPolicy,
) -> bool:
    if buffer.token_count >= policy.min_tokens:
        return False
    if merged.token_count <= policy.target_tokens:
        return True
    return policy.target_tokens < merged.token_count <= policy.max_tokens


def _tiny_warning(block: MergedBlock) -> ChunkingWarning:
    return ChunkingWarning(
        code=_TINY_CHUNK_UNMERGEABLE,
        message=(
            "Tiny prose chunk could not be merged without crossing a safe "
            "boundary or exceeding max_tokens"
        ),
        metadata={
            "atomic_block_indexes": block.atomic_block_indexes,
            "page_start": block.page_start,
            "page_end": block.page_end,
            "title_path": block.title_path,
            "token_count": block.token_count,
        },
    )


def _merge_safe_group(
    group: Sequence[AtomicBlock],
    policy: ChunkPolicy,
    token_counter: TokenCounter,
) -> tuple[list[MergedBlock], list[ChunkingWarning], int]:
    first = _build_merged_block((group[0],), token_counter)
    if not _is_mergeable_prose(group[0]):
        return [first], [], 0

    emitted: list[MergedBlock] = []
    warnings: list[ChunkingWarning] = []
    merge_count = 0
    buffer = first

    for atomic_block in group[1:]:
        next_block = _build_merged_block((atomic_block,), token_counter)
        if buffer.token_count < policy.min_tokens:
            forward = _combine(buffer, next_block, token_counter)
            if _can_merge_forward(buffer, forward, policy):
                buffer = forward
                merge_count += 1
                continue

            if emitted:
                backward = _combine(emitted[-1], buffer, token_counter)
                if backward.token_count <= policy.max_tokens:
                    emitted[-1] = backward
                    merge_count += 1
                    buffer = next_block
                    continue

            emitted.append(buffer)
            warnings.append(_tiny_warning(buffer))
            buffer = next_block
            continue

        emitted.append(buffer)
        buffer = next_block

    if buffer.token_count < policy.min_tokens and emitted:
        backward = _combine(emitted[-1], buffer, token_counter)
        if backward.token_count <= policy.max_tokens:
            emitted[-1] = backward
            merge_count += 1
            return emitted, warnings, merge_count

    emitted.append(buffer)
    if buffer.token_count < policy.min_tokens:
        warnings.append(_tiny_warning(buffer))
    return emitted, warnings, merge_count


def merge_small_blocks(
    blocks: Sequence[AtomicBlock],
    policy: ChunkPolicy,
    token_counter: TokenCounter,
) -> MergeResult:
    """Merge tiny compatible prose blocks within deterministic safe windows."""

    counter = require_token_counter(token_counter)
    merged_blocks: list[MergedBlock] = []
    warnings: list[ChunkingWarning] = []
    merge_count = 0

    for group in group_by_safe_boundary(blocks, policy):
        group_blocks, group_warnings, group_merge_count = _merge_safe_group(
            group,
            policy,
            counter,
        )
        merged_blocks.extend(group_blocks)
        warnings.extend(group_warnings)
        merge_count += group_merge_count

    return MergeResult(
        blocks=tuple(merged_blocks),
        warnings=tuple(warnings),
        merge_count=merge_count,
    )
