"""Deterministic recursive splitting for oversized prose candidates."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Pattern

from server.app.services.chunking.contracts import (
    AtomicBlock,
    BlockType,
    _freeze_json_mapping,
    to_json_value,
)
from server.app.services.chunking.merge import MergedBlock
from server.app.services.chunking.normalization import (
    NORMALIZATION_METADATA_KEY,
    normalized_fragment_provenance,
    normalized_segment_boundaries,
    normalized_span_to_original,
)
from server.app.services.chunking.policy import ChunkPolicy
from server.app.services.chunking.tokenizer import TokenCounter, require_token_counter

_SPLIT_NO_PROGRESS = "CHUNK_SPLIT_NO_PROGRESS"
_LOCATOR_SPAN_KEY = "_lingxi_chunk_span"


class SplitReason(str, Enum):
    """Stable reason describing the weakest boundary used by a split block."""

    UNSPLIT = "unsplit"
    STRUCTURAL_BLOCK = "structural_block"
    DOUBLE_NEWLINE = "double_newline"
    SINGLE_NEWLINE = "single_newline"
    SENTENCE = "sentence"
    PUNCTUATION_OR_WHITESPACE = "punctuation_or_whitespace"
    TOKEN_HARD_CUT = "token_hard_cut"


_REASON_DEPTH = {
    reason: depth
    for depth, reason in enumerate(
        (
            SplitReason.UNSPLIT,
            SplitReason.STRUCTURAL_BLOCK,
            SplitReason.DOUBLE_NEWLINE,
            SplitReason.SINGLE_NEWLINE,
            SplitReason.SENTENCE,
            SplitReason.PUNCTUATION_OR_WHITESPACE,
            SplitReason.TOKEN_HARD_CUT,
        )
    )
}


class ChunkSplitNoProgressError(RuntimeError):
    """Non-retryable guard failure when an oversized span cannot shrink."""

    def __init__(self, message: str, *, content: str) -> None:
        self.code = _SPLIT_NO_PROGRESS
        self.message = message
        self.retryable = False
        self.block_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        super().__init__(f"{self.code}: {message}; block_hash={self.block_hash}")


@dataclass(frozen=True)
class SplitBlock:
    """A bounded prose block with exact ranges into its merged source."""

    content: str
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

    def __post_init__(self) -> None:
        if not self.content or not self.content.strip():
            raise ValueError("SplitBlock content must not be empty")
        if self.token_count < 0:
            raise ValueError("SplitBlock token_count must be non-negative")
        if not 0 <= self.relative_char_start < self.relative_char_end:
            raise ValueError("SplitBlock relative character range is invalid")

        atomic_blocks = tuple(self.atomic_blocks)
        atomic_indexes = tuple(self.atomic_block_indexes)
        source_locators = tuple(
            _freeze_json_mapping(locator, field_name="SplitBlock source locator")
            for locator in self.source_locators
        )
        if not atomic_blocks or not source_locators:
            raise ValueError("SplitBlock requires source provenance")
        if not (
            len(atomic_blocks) == len(atomic_indexes) == len(source_locators)
        ):
            raise ValueError("SplitBlock provenance sequences must be aligned")
        if atomic_indexes != tuple(block.index for block in atomic_blocks):
            raise ValueError("SplitBlock indexes must match atomic blocks")

        object.__setattr__(self, "block_type", BlockType(self.block_type))
        object.__setattr__(self, "title_path", tuple(self.title_path))
        object.__setattr__(self, "source_locators", source_locators)
        object.__setattr__(self, "atomic_block_indexes", atomic_indexes)
        object.__setattr__(self, "atomic_blocks", atomic_blocks)
        object.__setattr__(self, "split_reason", SplitReason(self.split_reason))


@dataclass(frozen=True)
class RecursiveSplitResult:
    """Immutable output of recursive oversized-prose splitting."""

    blocks: tuple[SplitBlock, ...]
    split_count: int
    oversized_count: int = 0

    def __post_init__(self) -> None:
        blocks = tuple(self.blocks)
        if not blocks:
            raise ValueError("RecursiveSplitResult requires at least one block")
        if (
            not isinstance(self.split_count, int)
            or isinstance(self.split_count, bool)
            or self.split_count < 0
        ):
            raise ValueError("split_count must be a non-negative integer")
        if (
            not isinstance(self.oversized_count, int)
            or isinstance(self.oversized_count, bool)
            or self.oversized_count < 0
        ):
            raise ValueError("oversized_count must be a non-negative integer")
        object.__setattr__(self, "blocks", blocks)


@dataclass(frozen=True)
class _Span:
    start: int
    end: int
    reason: SplitReason
    normalization_fragment: bool = False


@dataclass(frozen=True)
class _AtomicLayout:
    block: AtomicBlock
    start: int
    end: int


@dataclass(frozen=True)
class _RegexLevel:
    reason: SplitReason
    pattern: Pattern[str]
    include_match_in_left: bool


_REGEX_LEVELS = (
    _RegexLevel(
        SplitReason.DOUBLE_NEWLINE,
        re.compile(r"(?:\r?\n){2,}"),
        False,
    ),
    _RegexLevel(
        SplitReason.SINGLE_NEWLINE,
        re.compile(r"\r?\n"),
        False,
    ),
    _RegexLevel(
        SplitReason.SENTENCE,
        re.compile(r"[。！？!?；;.]+(?:[\"'”’」』）)]*)"),
        True,
    ),
    _RegexLevel(
        SplitReason.PUNCTUATION_OR_WHITESPACE,
        re.compile(r"[，,、：:；;…]+|[ \t]+"),
        True,
    ),
)


def _trim_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start == end:
        return None
    return start, end


def _split_span_by_regex(
    text: str,
    span: _Span,
    level: _RegexLevel,
) -> list[_Span]:
    pieces: list[_Span] = []
    cursor = span.start
    for match in level.pattern.finditer(text, span.start, span.end):
        left_end = match.end() if level.include_match_in_left else match.start()
        trimmed = _trim_span(text, cursor, left_end)
        if trimmed is not None:
            pieces.append(_Span(*trimmed, level.reason))
        cursor = match.end()

    trimmed = _trim_span(text, cursor, span.end)
    if trimmed is not None:
        pieces.append(_Span(*trimmed, level.reason))
    return pieces


def _has_progress(
    text: str,
    original: _Span,
    pieces: Sequence[_Span],
    token_counter: TokenCounter,
) -> bool:
    if len(pieces) <= 1:
        return False
    original_tokens = token_counter.count(text[original.start : original.end])
    largest_piece = max(
        token_counter.count(text[piece.start : piece.end]) for piece in pieces
    )
    return largest_piece < original_tokens


def _hard_split_span(
    text: str,
    span: _Span,
    policy: ChunkPolicy,
    token_counter: TokenCounter,
) -> list[_Span]:
    source = text[span.start : span.end]
    parts = token_counter.split_by_token_limit(source, policy.max_tokens)
    if (
        not parts
        or any(not part for part in parts)
        or "".join(parts) != source
        or any(token_counter.count(part) > policy.max_tokens for part in parts)
        or (len(parts) == 1 and token_counter.count(source) > policy.max_tokens)
    ):
        raise ChunkSplitNoProgressError(
            "token hard split failed to shrink an oversized prose span",
            content=source,
        )

    pieces: list[_Span] = []
    cursor = span.start
    for part in parts:
        end = cursor + len(part)
        pieces.append(_Span(cursor, end, SplitReason.TOKEN_HARD_CUT))
        cursor = end
    if cursor != span.end:
        raise ChunkSplitNoProgressError(
            "token hard split produced inconsistent character ranges",
            content=source,
        )
    return pieces


def _split_recursively(
    text: str,
    span: _Span,
    policy: ChunkPolicy,
    token_counter: TokenCounter,
    *,
    level_index: int = 0,
) -> list[_Span]:
    source = text[span.start : span.end]
    if token_counter.count(source) <= policy.max_tokens:
        return [span]

    for next_level_index in range(level_index, len(_REGEX_LEVELS)):
        level = _REGEX_LEVELS[next_level_index]
        pieces = _split_span_by_regex(text, span, level)
        if not _has_progress(text, span, pieces, token_counter):
            continue

        bounded: list[_Span] = []
        for piece in pieces:
            bounded.extend(
                _split_recursively(
                    text,
                    piece,
                    policy,
                    token_counter,
                    level_index=next_level_index + 1,
                )
            )
        return bounded

    return _hard_split_span(text, span, policy, token_counter)


def _merged_normalization_boundaries(
    block: MergedBlock, layouts: Sequence[_AtomicLayout]
) -> tuple[int, ...]:
    boundaries = {0, len(block.content)}
    cursor = 0
    for layout in layouts:
        # Merge separators have no atomic provenance and are independently safe.
        boundaries.update(range(cursor, layout.start + 1))
        normalization = layout.block.metadata.get(NORMALIZATION_METADATA_KEY)
        if isinstance(normalization, Mapping):
            try:
                boundaries.update(
                    layout.start + boundary
                    for boundary in normalized_segment_boundaries(normalization)
                )
            except ValueError as exc:
                raise ChunkSplitNoProgressError(
                    str(exc), content=layout.block.content
                ) from exc
        else:
            boundaries.update(range(layout.start, layout.end + 1))
        cursor = layout.end
    boundaries.update(range(cursor, len(block.content) + 1))
    return tuple(sorted(boundaries))


def _bounded_normalization_spans(
    text: str,
    span: _Span,
    policy: ChunkPolicy,
    token_counter: TokenCounter,
    boundaries: Sequence[int],
) -> list[_Span]:
    legal = [
        boundary for boundary in boundaries if span.start <= boundary <= span.end
    ]
    if not legal or legal[0] != span.start or legal[-1] != span.end:
        raise ChunkSplitNoProgressError(
            "normalization-aligned span has incomplete legal boundaries",
            content=text[span.start : span.end],
        )

    pieces: list[_Span] = []
    boundary_index = 0
    while boundary_index < len(legal) - 1:
        start = legal[boundary_index]
        best_index = boundary_index
        probe_index = boundary_index + 1
        while probe_index < len(legal):
            candidate = text[start : legal[probe_index]]
            if token_counter.count(candidate) > policy.max_tokens:
                break
            best_index = probe_index
            probe_index += 1
        if best_index > boundary_index:
            end = legal[best_index]
            reason = (
                span.reason
                if start == span.start and end == span.end
                else SplitReason.TOKEN_HARD_CUT
            )
            pieces.append(_Span(start, end, reason))
            boundary_index = best_index
            continue

        # One canonical normalization segment exceeds max_tokens. Preserve the
        # containing original segment as explicit provenance while splitting only
        # in normalized coordinate space; never claim an irreversible raw slice.
        segment_end = legal[boundary_index + 1]
        source = text[start:segment_end]
        parts = token_counter.split_by_token_limit(source, policy.max_tokens)
        if (
            not parts
            or any(not part for part in parts)
            or "".join(parts) != source
            or any(token_counter.count(part) > policy.max_tokens for part in parts)
            or (len(parts) == 1 and token_counter.count(source) > policy.max_tokens)
        ):
            raise ChunkSplitNoProgressError(
                "one normalization segment cannot be safely split by the tokenizer",
                content=source,
            )
        cursor = start
        for part in parts:
            end = cursor + len(part)
            pieces.append(
                _Span(
                    cursor,
                    end,
                    SplitReason.TOKEN_HARD_CUT,
                    normalization_fragment=True,
                )
            )
            cursor = end
        boundary_index += 1
    return pieces


def _align_spans_to_normalization(
    text: str,
    spans: Sequence[_Span],
    policy: ChunkPolicy,
    token_counter: TokenCounter,
    boundaries: Sequence[int],
) -> list[_Span]:
    boundary_set = set(boundaries)
    expanded: list[_Span] = []
    for span in spans:
        if span.normalization_fragment:
            expanded.append(span)
            continue
        start = span.start
        end = span.end
        if start not in boundary_set:
            start = max(boundary for boundary in boundaries if boundary < start)
        if end not in boundary_set:
            end = min(boundary for boundary in boundaries if boundary > end)
        candidate = _Span(start, end, span.reason)
        if expanded and candidate.start < expanded[-1].end:
            previous = expanded.pop()
            candidate = _Span(
                previous.start,
                max(previous.end, candidate.end),
                _combine_reason((previous, candidate)),
            )
        expanded.append(candidate)

    bounded: list[_Span] = []
    for span in expanded:
        if token_counter.count(text[span.start : span.end]) <= policy.max_tokens:
            bounded.append(span)
        else:
            bounded.extend(
                _bounded_normalization_spans(
                    text, span, policy, token_counter, boundaries
                )
            )
    return bounded


def _atomic_layouts(block: MergedBlock) -> tuple[_AtomicLayout, ...]:
    layouts: list[_AtomicLayout] = []
    cursor = 0
    for atomic_block in block.atomic_blocks:
        start = block.content.find(atomic_block.content, cursor)
        if start < 0:
            raise ChunkSplitNoProgressError(
                "merged content cannot be mapped back to its atomic blocks",
                content=block.content,
            )
        end = start + len(atomic_block.content)
        layouts.append(_AtomicLayout(atomic_block, start, end))
        cursor = end
    return tuple(layouts)


def _structure_spans(
    block: MergedBlock,
    layouts: Sequence[_AtomicLayout],
    token_counter: TokenCounter,
) -> list[_Span] | None:
    if len(layouts) <= 1:
        return None
    pieces = [
        _Span(layout.start, layout.end, SplitReason.STRUCTURAL_BLOCK)
        for layout in layouts
    ]
    original = _Span(0, len(block.content), SplitReason.UNSPLIT)
    if not _has_progress(block.content, original, pieces, token_counter):
        return None
    return pieces


def _combine_reason(spans: Sequence[_Span]) -> SplitReason:
    return max(spans, key=lambda span: _REASON_DEPTH[span.reason]).reason


def _pack_spans(
    text: str,
    spans: Sequence[_Span],
    policy: ChunkPolicy,
    token_counter: TokenCounter,
    *,
    structural_boundaries: Sequence[int],
) -> list[_Span]:
    if not spans:
        raise ChunkSplitNoProgressError(
            "recursive split produced no non-empty spans",
            content=text,
        )

    packed: list[_Span] = []
    current_parts: list[_Span] = [spans[0]]
    current = spans[0]

    for next_span in spans[1:]:
        candidate_text = text[current.start : next_span.end]
        candidate_tokens = token_counter.count(candidate_text)
        current_tokens = token_counter.count(text[current.start : current.end])
        if candidate_tokens <= policy.target_tokens or (
            current_tokens < policy.min_tokens
            and candidate_tokens <= policy.max_tokens
        ):
            current_parts.append(next_span)
            current = _Span(
                current.start,
                next_span.end,
                _combine_reason(current_parts),
            )
            continue

        packed.append(current)
        current_parts = [next_span]
        current = next_span

    packed.append(current)
    return _rebalance_tiny_tail(
        text,
        packed,
        policy,
        token_counter,
        structural_boundaries=structural_boundaries,
    )


def _rebalance_candidate(
    text: str,
    left_range: tuple[int, int] | None,
    right_range: tuple[int, int] | None,
    reason: SplitReason,
    policy: ChunkPolicy,
    token_counter: TokenCounter,
) -> tuple[tuple[int, int, int], _Span, _Span] | None:
    if left_range is None or right_range is None:
        return None
    left_text = text[left_range[0] : left_range[1]]
    right_text = text[right_range[0] : right_range[1]]
    left_tokens = token_counter.count(left_text)
    right_tokens = token_counter.count(right_text)
    if not (
        policy.min_tokens <= left_tokens <= policy.max_tokens
        and policy.min_tokens <= right_tokens <= policy.max_tokens
    ):
        return None
    return (
        (
            abs(left_tokens - policy.target_tokens),
            abs(right_tokens - policy.target_tokens),
            -left_tokens,
        ),
        _Span(*left_range, reason),
        _Span(*right_range, reason),
    )


def _best_rebalance_candidate(
    candidates: Sequence[tuple[tuple[int, int, int], _Span, _Span]],
) -> tuple[_Span, _Span] | None:
    if not candidates:
        return None
    best = min(candidates, key=lambda candidate: candidate[0])
    return best[1], best[2]


def _natural_rebalance_pair(
    text: str,
    previous: _Span,
    tail: _Span,
    policy: ChunkPolicy,
    token_counter: TokenCounter,
    structural_boundaries: Sequence[int],
) -> tuple[_Span, _Span] | None:
    structural_candidates = []
    for boundary in structural_boundaries:
        if not previous.start < boundary < tail.end:
            continue
        candidate = _rebalance_candidate(
            text,
            _trim_span(text, previous.start, boundary),
            _trim_span(text, boundary, tail.end),
            SplitReason.STRUCTURAL_BLOCK,
            policy,
            token_counter,
        )
        if candidate is not None:
            structural_candidates.append(candidate)
    best = _best_rebalance_candidate(structural_candidates)
    if best is not None:
        return best

    for level in _REGEX_LEVELS:
        level_candidates = []
        for match in level.pattern.finditer(text, previous.start, tail.end):
            left_end = match.end() if level.include_match_in_left else match.start()
            candidate = _rebalance_candidate(
                text,
                _trim_span(text, previous.start, left_end),
                _trim_span(text, match.end(), tail.end),
                level.reason,
                policy,
                token_counter,
            )
            if candidate is not None:
                level_candidates.append(candidate)
        best = _best_rebalance_candidate(level_candidates)
        if best is not None:
            return best
    return None


def _bounded_hard_split_limits(
    policy: ChunkPolicy,
    combined_tokens: int,
) -> tuple[int, ...]:
    def bounded(value: int) -> int:
        return max(policy.min_tokens, min(policy.max_tokens, value))

    raw_limits = (
        policy.target_tokens,
        bounded(combined_tokens // 2),
        bounded(combined_tokens - policy.min_tokens),
        bounded(combined_tokens - policy.max_tokens),
        bounded(policy.target_tokens - 1),
        bounded(policy.target_tokens + 1),
        policy.max_tokens,
        policy.min_tokens,
    )
    return tuple(dict.fromkeys(raw_limits))


def _nearest_split_points(
    boundaries: Sequence[int],
    desired_points: Sequence[int],
) -> tuple[int, ...]:
    nearest = (
        min(
            boundaries,
            key=lambda boundary: (abs(boundary - desired), boundary),
        )
        for desired in desired_points
    )
    return tuple(dict.fromkeys(nearest))


def _token_hard_rebalance_pair(
    text: str,
    previous: _Span,
    tail: _Span,
    policy: ChunkPolicy,
    token_counter: TokenCounter,
    combined_tokens: int,
) -> tuple[_Span, _Span] | None:
    combined_text = text[previous.start : tail.end]
    for limit in _bounded_hard_split_limits(policy, combined_tokens):
        parts = token_counter.split_by_token_limit(combined_text, limit)
        if not parts or any(not part for part in parts):
            continue
        if "".join(parts) != combined_text or len(parts) < 2:
            continue

        part_boundaries = []
        split_at = previous.start
        for part in parts[:-1]:
            split_at += len(part)
            part_boundaries.append(split_at)
        desired_points = _bounded_character_split_points(
            previous,
            tail,
            policy,
            combined_tokens,
        )

        candidates = []
        for split_at in _nearest_split_points(
            part_boundaries,
            desired_points,
        ):
            candidate = _rebalance_candidate(
                text,
                _trim_span(text, previous.start, split_at),
                _trim_span(text, split_at, tail.end),
                SplitReason.TOKEN_HARD_CUT,
                policy,
                token_counter,
            )
            if candidate is not None:
                candidates.append(candidate)
        best = _best_rebalance_candidate(candidates)
        if best is not None:
            return best
    return None


def _bounded_character_split_points(
    previous: _Span,
    tail: _Span,
    policy: ChunkPolicy,
    combined_tokens: int,
) -> tuple[int, ...]:
    span_length = tail.end - previous.start
    token_targets = (
        policy.target_tokens,
        combined_tokens - policy.target_tokens,
        policy.min_tokens,
        combined_tokens - policy.min_tokens,
        policy.max_tokens,
        combined_tokens - policy.max_tokens,
    )
    estimated = [
        previous.start + round(span_length * target / combined_tokens)
        for target in token_targets
        if 0 < target < combined_tokens
    ]
    anchors = [previous.end, previous.start + (span_length // 2), *estimated]
    candidates = (
        point + offset
        for point in anchors
        for offset in (0, -1, 1, -2, 2)
        if previous.start < point + offset < tail.end
    )
    return tuple(dict.fromkeys(candidates))


def _verified_character_hard_rebalance_pair(
    text: str,
    previous: _Span,
    tail: _Span,
    policy: ChunkPolicy,
    token_counter: TokenCounter,
    combined_tokens: int,
) -> tuple[_Span, _Span] | None:
    candidates = []
    for split_at in _bounded_character_split_points(
        previous,
        tail,
        policy,
        combined_tokens,
    ):
        candidate = _rebalance_candidate(
            text,
            _trim_span(text, previous.start, split_at),
            _trim_span(text, split_at, tail.end),
            SplitReason.TOKEN_HARD_CUT,
            policy,
            token_counter,
        )
        if candidate is not None:
            candidates.append(candidate)
    return _best_rebalance_candidate(candidates)


def _rebalance_tiny_tail(
    text: str,
    spans: list[_Span],
    policy: ChunkPolicy,
    token_counter: TokenCounter,
    *,
    structural_boundaries: Sequence[int],
) -> list[_Span]:
    if len(spans) < 2:
        return spans

    previous = spans[-2]
    tail = spans[-1]
    tail_tokens = token_counter.count(text[tail.start : tail.end])
    if tail_tokens >= policy.min_tokens:
        return spans

    combined_text = text[previous.start : tail.end]
    combined_tokens = token_counter.count(combined_text)
    if combined_tokens <= policy.max_tokens:
        reason = _combine_reason((previous, tail))
        return spans[:-2] + [_Span(previous.start, tail.end, reason)]

    rebalanced = _natural_rebalance_pair(
        text,
        previous,
        tail,
        policy,
        token_counter,
        structural_boundaries,
    )
    if rebalanced is None:
        rebalanced = _token_hard_rebalance_pair(
            text,
            previous,
            tail,
            policy,
            token_counter,
            combined_tokens,
        )
    if rebalanced is None:
        rebalanced = _verified_character_hard_rebalance_pair(
            text,
            previous,
            tail,
            policy,
            token_counter,
            combined_tokens,
        )
    if rebalanced is None:
        return spans
    return spans[:-2] + [rebalanced[0], rebalanced[1]]


def _annotated_provenance(
    block: MergedBlock,
    layouts: Sequence[_AtomicLayout],
    span: _Span,
    token_counter: TokenCounter,
) -> tuple[
    tuple[AtomicBlock, ...],
    tuple[Mapping[str, Any], ...],
]:
    atomic_blocks: list[AtomicBlock] = []
    locators: list[Mapping[str, Any]] = []
    for layout in layouts:
        overlap_start = max(span.start, layout.start)
        overlap_end = min(span.end, layout.end)
        if overlap_start >= overlap_end:
            continue

        source_locator = to_json_value(layout.block.source_locator)
        if _LOCATOR_SPAN_KEY in source_locator:
            raise ChunkSplitNoProgressError(
                f"source locator reserves key {_LOCATOR_SPAN_KEY}",
                content=block.content,
            )
        normalized_start = overlap_start - layout.start
        normalized_end = overlap_end - layout.start
        normalization = layout.block.metadata.get(NORMALIZATION_METADATA_KEY)
        original_start = normalized_start
        original_end = normalized_end
        normalization_version = "identity-v1"
        normalization_work_units = len(layout.block.content)
        if isinstance(normalization, Mapping):
            normalization_version = str(
                normalization.get("version", "unknown")
            )
            raw_work_units = normalization.get("normalizationWorkUnits", 0)
            if not isinstance(raw_work_units, int) or isinstance(raw_work_units, bool):
                raise ChunkSplitNoProgressError(
                    "normalized atomic block has invalid normalization work units",
                    content=block.content,
                )
            normalization_work_units = raw_work_units
            if not span.normalization_fragment:
                try:
                    original_start, original_end = normalized_span_to_original(
                        normalization,
                        normalized_start,
                        normalized_end,
                        expected_normalized=layout.block.content[
                            normalized_start:normalized_end
                        ],
                    )
                except ValueError as exc:
                    raise ChunkSplitNoProgressError(
                        str(exc),
                        content=block.content,
                    ) from exc
        locator_span: dict[str, Any] = {
            "split_reason": span.reason.value,
            "coordinate_space": "original_atomic",
            "normalization_version": normalization_version,
            "normalization_work_units": normalization_work_units,
            "merged_coordinate_space": "normalized_merged",
            "merged_char_start": overlap_start,
            "merged_char_end": overlap_end,
            "normalized_atomic_char_start": normalized_start,
            "normalized_atomic_char_end": normalized_end,
        }
        if span.normalization_fragment and isinstance(normalization, Mapping):
            try:
                fragment = normalized_fragment_provenance(
                    normalization, normalized_start, normalized_end
                )
            except ValueError as exc:
                raise ChunkSplitNoProgressError(
                    str(exc), content=block.content[span.start : span.end]
                ) from exc
            locator_span.update(
                {
                    "coordinate_space": fragment["coordinateSpace"],
                    "provenance_mode": fragment["provenanceMode"],
                    "original_segment_char_start": fragment[
                        "originalSegmentStart"
                    ],
                    "original_segment_char_end": fragment["originalSegmentEnd"],
                    "normalization_segment_char_start": fragment[
                        "normalizedSegmentStart"
                    ],
                    "normalization_segment_char_end": fragment[
                        "normalizedSegmentEnd"
                    ],
                }
            )
        else:
            locator_span.update(
                {
                    "atomic_char_start": original_start,
                    "atomic_char_end": original_end,
                }
            )
        source_locator[_LOCATOR_SPAN_KEY] = locator_span
        atomic_blocks.append(layout.block)
        locators.append(source_locator)

    if not atomic_blocks:
        raise ChunkSplitNoProgressError(
            "split span does not overlap any atomic source block",
            content=block.content[span.start : span.end],
        )
    return tuple(atomic_blocks), tuple(locators)


def _build_split_block(
    block: MergedBlock,
    layouts: Sequence[_AtomicLayout],
    span: _Span,
    token_counter: TokenCounter,
) -> SplitBlock:
    atomic_blocks, source_locators = _annotated_provenance(
        block,
        layouts,
        span,
        token_counter,
    )
    pages = [
        atomic_block.page_no
        for atomic_block in atomic_blocks
        if atomic_block.page_no is not None
    ]
    content = block.content[span.start : span.end]
    return SplitBlock(
        content=content,
        block_type=block.block_type,
        title_path=block.title_path,
        token_count=token_counter.count(content),
        page_start=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
        source_locators=source_locators,
        atomic_block_indexes=tuple(
            atomic_block.index for atomic_block in atomic_blocks
        ),
        atomic_blocks=atomic_blocks,
        split_reason=span.reason,
        relative_char_start=span.start,
        relative_char_end=span.end,
    )


def split_oversized_prose(
    block: MergedBlock,
    policy: ChunkPolicy,
    token_counter: TokenCounter,
) -> RecursiveSplitResult:
    """Split prose with stable structural-to-token boundary degradation.

    Character ranges use Python Unicode string indexes (Unicode code points),
    are half-open ``[start, end)``, and are relative to ``block.content``.
    ``token_count`` is measured on each emitted block independently; global token
    offsets are intentionally omitted because BPE prefix counts are not monotonic.
    """

    counter = require_token_counter(token_counter)
    layouts = _atomic_layouts(block)
    actual_tokens = counter.count(block.content)
    if actual_tokens <= policy.max_tokens:
        spans = [_Span(0, len(block.content), SplitReason.UNSPLIT)]
    else:
        structural = _structure_spans(block, layouts, counter)
        initial_spans = structural or [
            _Span(0, len(block.content), SplitReason.UNSPLIT)
        ]
        leaves: list[_Span] = []
        for initial in initial_spans:
            leaves.extend(
                _split_recursively(
                    block.content,
                    initial,
                    policy,
                    counter,
                )
            )
        spans = _pack_spans(
            block.content,
            leaves,
            policy,
            counter,
            structural_boundaries=tuple(
                layout.start for layout in layouts[1:]
            ),
        )

    spans = _align_spans_to_normalization(
        block.content,
        spans,
        policy,
        counter,
        _merged_normalization_boundaries(block, layouts),
    )
    split_blocks = tuple(
        _build_split_block(block, layouts, span, counter) for span in spans
    )
    if any(
        candidate.token_count > policy.max_tokens for candidate in split_blocks
    ):
        raise ChunkSplitNoProgressError(
            "recursive split emitted a block over max_tokens",
            content=block.content,
        )
    return RecursiveSplitResult(
        blocks=split_blocks,
        split_count=max(0, len(split_blocks) - 1),
        oversized_count=int(actual_tokens > policy.max_tokens),
    )
