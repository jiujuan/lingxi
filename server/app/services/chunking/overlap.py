"""Bounded sentence-level overlap for recursively split plain prose."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from server.app.services.chunking.contracts import (
    AtomicBlock,
    BlockType,
    _freeze_json_mapping,
    to_json_value,
)
from server.app.services.chunking.policy import ChunkPolicy
from server.app.services.chunking.recursive_splitter import (
    RecursiveSplitResult,
    SplitBlock,
    SplitReason,
)
from server.app.services.chunking.tokenizer import TokenCounter, require_token_counter

_OVERLAP_SEPARATOR = "\n\n"
_OVERLAP_ELIGIBLE_REASONS = frozenset(
    {
        SplitReason.SENTENCE,
        SplitReason.PUNCTUATION_OR_WHITESPACE,
        SplitReason.TOKEN_HARD_CUT,
    }
)
_SENTENCE_TERMINATOR_RE = re.compile(r"[。！？!?；;.]+(?:[\"'”’」』）)]*)")


@dataclass(frozen=True)
class OverlapBlock:
    """A child draft whose evidence span excludes its repeated prefix."""

    content: str
    unique_content: str
    block_type: BlockType
    title_path: tuple[str, ...]
    token_count: int
    page_start: int | None
    page_end: int | None
    source_locators: tuple[Mapping[str, Any], ...]
    atomic_block_indexes: tuple[int, ...]
    atomic_blocks: tuple[AtomicBlock, ...]
    split_reason: SplitReason
    relative_char_start: int
    relative_char_end: int
    overlap_prefix: str = ""
    overlap_prefix_tokens: int = 0
    overlap_source_char_start: int | None = None
    overlap_source_char_end: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.content or not self.content.strip():
            raise ValueError("OverlapBlock content must not be empty")
        if not self.unique_content or not self.unique_content.strip():
            raise ValueError("OverlapBlock unique_content must not be empty")
        if self.token_count < 0:
            raise ValueError("OverlapBlock token_count must be non-negative")
        if not 0 <= self.relative_char_start < self.relative_char_end:
            raise ValueError("OverlapBlock relative character range is invalid")
        if self.overlap_prefix_tokens < 0:
            raise ValueError("overlap_prefix_tokens must be non-negative")

        atomic_blocks = tuple(self.atomic_blocks)
        atomic_indexes = tuple(self.atomic_block_indexes)
        source_locators = tuple(
            _freeze_json_mapping(
                locator,
                field_name="OverlapBlock source locator",
            )
            for locator in self.source_locators
        )
        if not atomic_blocks or not source_locators:
            raise ValueError("OverlapBlock requires source provenance")
        if not (
            len(atomic_blocks) == len(atomic_indexes) == len(source_locators)
        ):
            raise ValueError("OverlapBlock provenance sequences must be aligned")
        if atomic_indexes != tuple(block.index for block in atomic_blocks):
            raise ValueError("OverlapBlock indexes must match atomic blocks")

        has_prefix = bool(self.overlap_prefix)
        has_span = (
            self.overlap_source_char_start is not None
            and self.overlap_source_char_end is not None
        )
        if has_prefix:
            if self.overlap_prefix_tokens <= 0 or not has_span:
                raise ValueError("overlap prefix requires token count and source span")
            source_start = self.overlap_source_char_start
            source_end = self.overlap_source_char_end
            if source_start is None or source_end is None or not (
                0 <= source_start < source_end <= self.relative_char_start
            ):
                raise ValueError("overlap source character range is invalid")
            if self.content != (
                self.overlap_prefix + _OVERLAP_SEPARATOR + self.unique_content
            ):
                raise ValueError("OverlapBlock content does not match its prefix")
        elif (
            self.overlap_prefix_tokens != 0
            or self.overlap_source_char_start is not None
            or self.overlap_source_char_end is not None
            or self.content != self.unique_content
        ):
            raise ValueError("empty overlap prefix must not carry overlap metadata")

        raw_metadata = self.metadata
        if not isinstance(raw_metadata, Mapping):
            raise ValueError("OverlapBlock metadata must be a mapping")
        normalized_metadata = to_json_value(raw_metadata)
        if has_prefix:
            expected_overlap = {
                "prefix_token_count": self.overlap_prefix_tokens,
                "source_relative_char_start": source_start,
                "source_relative_char_end": source_end,
            }
            if (
                "overlap" in normalized_metadata
                and normalized_metadata["overlap"] != expected_overlap
            ):
                raise ValueError(
                    "OverlapBlock overlap metadata conflicts with typed fields"
                )
            normalized_metadata["overlap"] = expected_overlap
        elif "overlap" in normalized_metadata:
            raise ValueError(
                "OverlapBlock overlap metadata conflicts with empty typed fields"
            )

        object.__setattr__(self, "block_type", BlockType(self.block_type))
        object.__setattr__(self, "title_path", tuple(self.title_path))
        object.__setattr__(self, "source_locators", source_locators)
        object.__setattr__(self, "atomic_block_indexes", atomic_indexes)
        object.__setattr__(self, "atomic_blocks", atomic_blocks)
        object.__setattr__(self, "split_reason", SplitReason(self.split_reason))
        object.__setattr__(
            self,
            "metadata",
            _freeze_json_mapping(
                normalized_metadata,
                field_name="OverlapBlock metadata",
            ),
        )


@dataclass(frozen=True)
class OverlapResult:
    """Immutable result for one recursively split source unit."""

    blocks: tuple[OverlapBlock, ...]
    overlap_count: int

    def __post_init__(self) -> None:
        blocks = tuple(self.blocks)
        if not blocks:
            raise ValueError("OverlapResult requires at least one block")
        if (
            not isinstance(self.overlap_count, int)
            or isinstance(self.overlap_count, bool)
            or self.overlap_count < 0
        ):
            raise ValueError("overlap_count must be a non-negative integer")
        if self.overlap_count != sum(
            bool(block.overlap_prefix) for block in blocks
        ):
            raise ValueError("overlap_count does not match blocks")
        object.__setattr__(self, "blocks", blocks)


@dataclass(frozen=True)
class _PrefixSelection:
    content: str
    token_count: int
    source_char_start: int
    source_char_end: int
    rendered_content: str
    rendered_token_count: int


def _base_block(block: SplitBlock) -> OverlapBlock:
    return OverlapBlock(
        content=block.content,
        unique_content=block.content,
        block_type=block.block_type,
        title_path=block.title_path,
        token_count=block.token_count,
        page_start=block.page_start,
        page_end=block.page_end,
        source_locators=block.source_locators,
        atomic_block_indexes=block.atomic_block_indexes,
        atomic_blocks=block.atomic_blocks,
        split_reason=block.split_reason,
        relative_char_start=block.relative_char_start,
        relative_char_end=block.relative_char_end,
        metadata={},
    )


def _shares_atomic_source(previous: SplitBlock, current: SplitBlock) -> bool:
    """Return whether adjacent spans retain a common immutable AtomicBlock."""

    previous_by_index = {
        block.index: block for block in previous.atomic_blocks
    }
    return any(
        previous_by_index.get(block.index) == block
        for block in current.atomic_blocks
    )


def _can_overlap(previous: SplitBlock, current: SplitBlock) -> bool:
    return (
        previous.block_type is BlockType.TEXT
        and current.block_type is BlockType.TEXT
        and previous.split_reason in _OVERLAP_ELIGIBLE_REASONS
        and current.split_reason in _OVERLAP_ELIGIBLE_REASONS
        and previous.title_path == current.title_path
        and previous.relative_char_end <= current.relative_char_start
        and _shares_atomic_source(previous, current)
    )


def _complete_sentence_starts(
    text: str,
    end: int,
    *,
    minimum_start: int,
) -> tuple[int, ...]:
    """Return suffix starts whose text ends at a complete sentence boundary."""

    matches = tuple(_SENTENCE_TERMINATOR_RE.finditer(text, 0, end))
    if not matches or matches[-1].end() != end:
        return ()

    starts = [minimum_start] if minimum_start == 0 else []
    for match in matches[:-1]:
        start = match.end()
        while start < end and text[start].isspace():
            start += 1
        if minimum_start <= start < end:
            starts.append(start)
    return tuple(dict.fromkeys(starts))


def _selection_for_start(
    previous: SplitBlock,
    current: SplitBlock,
    start: int,
    end: int,
    policy: ChunkPolicy,
    token_counter: TokenCounter,
) -> _PrefixSelection | None:
    prefix = previous.content[start:end]
    if not prefix or not prefix.strip():
        return None

    prefix_tokens = token_counter.count(prefix)
    if prefix_tokens <= 0 or prefix_tokens > policy.overlap_tokens:
        return None

    rendered = prefix + _OVERLAP_SEPARATOR + current.content
    rendered_tokens = token_counter.count(rendered)
    if rendered_tokens > policy.max_tokens:
        return None

    return _PrefixSelection(
        content=prefix,
        token_count=prefix_tokens,
        source_char_start=previous.relative_char_start + start,
        source_char_end=previous.relative_char_start + end,
        rendered_content=rendered,
        rendered_token_count=rendered_tokens,
    )


def _bounded_suffix_window_start(
    text: str,
    end: int,
    overlap_tokens: int,
    token_counter: TokenCounter,
) -> int:
    """Bound suffix probing to at most two overlap-sized tokenizer pieces.

    Splitting the source once is near-linear in the source size. The remaining
    character probes are independent of ``max_tokens`` and bounded by the final
    two overlap-sized pieces instead of rescanning an entire 800-token child.
    """

    source = text[:end]
    parts = token_counter.split_by_token_limit(source, overlap_tokens)
    if not parts or any(not part for part in parts) or "".join(parts) != source:
        raise ValueError("TokenCounter returned an invalid overlap split")
    bounded_tail = ""
    for part in reversed(parts):
        bounded_tail = part + bounded_tail
        if token_counter.count(bounded_tail) > overlap_tokens:
            break
    return end - len(bounded_tail)


def _select_prefix(
    previous: SplitBlock,
    current: SplitBlock,
    policy: ChunkPolicy,
    token_counter: TokenCounter,
) -> _PrefixSelection | None:
    if policy.overlap_tokens == 0:
        return None

    end = len(previous.content.rstrip())
    if end == 0:
        return None
    minimum_start = _bounded_suffix_window_start(
        previous.content,
        end,
        policy.overlap_tokens,
        token_counter,
    )

    for start in _complete_sentence_starts(
        previous.content,
        end,
        minimum_start=minimum_start,
    ):
        selection = _selection_for_start(
            previous,
            current,
            start,
            end,
            policy,
            token_counter,
        )
        if selection is not None:
            return selection

    # A long final sentence, punctuation-free span, or tight child budget falls
    # back to the longest suffix in a tokenizer-bounded tail window.
    for start in range(minimum_start, end):
        selection = _selection_for_start(
            previous,
            current,
            start,
            end,
            policy,
            token_counter,
        )
        if selection is not None:
            return selection
    return None


def _with_overlap(block: SplitBlock, selection: _PrefixSelection) -> OverlapBlock:
    return OverlapBlock(
        content=selection.rendered_content,
        unique_content=block.content,
        block_type=block.block_type,
        title_path=block.title_path,
        token_count=selection.rendered_token_count,
        page_start=block.page_start,
        page_end=block.page_end,
        source_locators=block.source_locators,
        atomic_block_indexes=block.atomic_block_indexes,
        atomic_blocks=block.atomic_blocks,
        split_reason=block.split_reason,
        relative_char_start=block.relative_char_start,
        relative_char_end=block.relative_char_end,
        overlap_prefix=selection.content,
        overlap_prefix_tokens=selection.token_count,
        overlap_source_char_start=selection.source_char_start,
        overlap_source_char_end=selection.source_char_end,
    )


def apply_prose_overlap(
    result: RecursiveSplitResult,
    policy: ChunkPolicy,
    token_counter: TokenCounter,
) -> OverlapResult:
    """Add bounded overlap within one oversized plain-prose split result.

    The returned block keeps the input block's relative character range and
    source locators as its unique evidence. Repeated prefix provenance is stored
    only in overlap metadata, so retrieval deduplication can use the unchanged
    source span instead of treating repeated text as new evidence.
    """

    counter = require_token_counter(token_counter)
    output = [_base_block(result.blocks[0])]
    source_was_split = result.split_count > 0 and len(result.blocks) > 1

    for previous, current in zip(result.blocks, result.blocks[1:]):
        if not source_was_split or not _can_overlap(previous, current):
            output.append(_base_block(current))
            continue
        selection = _select_prefix(previous, current, policy, counter)
        output.append(
            _with_overlap(current, selection)
            if selection is not None
            else _base_block(current)
        )

    return OverlapResult(
        blocks=tuple(output),
        overlap_count=sum(bool(block.overlap_prefix) for block in output),
    )
