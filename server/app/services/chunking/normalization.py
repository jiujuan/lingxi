"""Deterministic Unicode normalization with original-coordinate provenance."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

NORMALIZATION_METADATA_KEY = "_lingxi_normalization"
NORMALIZATION_VERSION = "nfc-lf-strip-v2"


@dataclass(frozen=True)
class _SourceUnit:
    value: str
    original_start: int
    original_end: int
    source_unit_id: int
    segment_id: int = -1


class _Segments:
    def __init__(self) -> None:
        self.parent: list[int] = []
        self.start: list[int] = []
        self.end: list[int] = []

    def add(self, start: int, end: int) -> int:
        segment_id = len(self.parent)
        self.parent.append(segment_id)
        self.start.append(start)
        self.end.append(end)
        return segment_id

    def find(self, segment_id: int) -> int:
        root = segment_id
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[segment_id] != segment_id:
            parent = self.parent[segment_id]
            self.parent[segment_id] = root
            segment_id = parent
        return root

    def union(self, left: int, right: int) -> int:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return left_root
        # Always retain the earlier stable id so output is deterministic.
        root, merged = sorted((left_root, right_root))
        self.parent[merged] = root
        self.start[root] = min(self.start[root], self.start[merged])
        self.end[root] = max(self.end[root], self.end[merged])
        return root


def _line_ending_units(text: str) -> tuple[list[_SourceUnit], int]:
    units: list[_SourceUnit] = []
    index = 0
    work_units = 0
    while index < len(text):
        work_units += 1
        if text.startswith("\r\n", index):
            units.append(_SourceUnit("\n", index, index + 2, len(units)))
            index += 2
        elif text[index] == "\r":
            units.append(_SourceUnit("\n", index, index + 1, len(units)))
            index += 1
        else:
            units.append(_SourceUnit(text[index], index, index + 1, len(units)))
            index += 1
    return units, work_units


def _starts_with_nonstarter(value: str) -> bool:
    """Compatibility helper kept bounded to one caller-supplied code point."""

    decomposed = unicodedata.normalize("NFD", value)
    return bool(decomposed) and unicodedata.combining(decomposed[0]) != 0


def _canonical_decompose(
    units: Sequence[_SourceUnit],
) -> tuple[list[_SourceUnit], int]:
    decomposed: list[_SourceUnit] = []
    work_units = 0
    for unit in units:
        # The normalize input is always one code point. Unicode canonical
        # decomposition expansion is bounded independently of hostile run length.
        for value in unicodedata.normalize("NFD", unit.value):
            decomposed.append(
                _SourceUnit(
                    value,
                    unit.original_start,
                    unit.original_end,
                    unit.source_unit_id,
                )
            )
            work_units += 1
    return decomposed, work_units


def _stable_ccc_order(values: Sequence[_SourceUnit]) -> list[_SourceUnit]:
    if len(values) <= 1:
        return list(values)
    if unicodedata.combining(values[0].value) == 0:
        starter = [values[0]]
        marks = values[1:]
    else:
        starter = []
        marks = values
    buckets: list[list[_SourceUnit]] = [[] for _ in range(256)]
    for value in marks:
        buckets[unicodedata.combining(value.value)].append(value)
    return [*starter, *(value for bucket in buckets for value in bucket)]


def _canonical_order_and_segments(
    decomposed: Sequence[_SourceUnit],
    segments: _Segments,
) -> tuple[list[_SourceUnit], int]:
    ordered: list[_SourceUnit] = []
    current: list[_SourceUnit] = []
    source_segments: dict[int, int] = {}
    work_units = 0

    def flush() -> None:
        nonlocal current, work_units
        if not current:
            return
        ordered_cluster = _stable_ccc_order(current)
        segment_id = segments.add(
            min(unit.original_start for unit in current),
            max(unit.original_end for unit in current),
        )
        # A single original logical unit can canonically decompose into more
        # than one starter (CCC=0). Canonical ordering must still treat those
        # starters separately, but provenance must not expose an irreversible
        # boundary inside the one original unit. Union every canonical cluster
        # that contains output from the same stable source-unit identity.
        for source_unit_id in dict.fromkeys(
            unit.source_unit_id for unit in current
        ):
            previous_segment = source_segments.get(source_unit_id)
            if previous_segment is not None:
                segment_id = segments.union(previous_segment, segment_id)
            source_segments[source_unit_id] = segment_id
        ordered.extend(
            _SourceUnit(
                unit.value,
                unit.original_start,
                unit.original_end,
                unit.source_unit_id,
                segment_id,
            )
            for unit in ordered_cluster
        )
        work_units += len(current)
        current = []

    for unit in decomposed:
        if current and unicodedata.combining(unit.value) == 0:
            flush()
        current.append(unit)
    flush()
    return ordered, work_units


def _canonical_compose(
    ordered: Sequence[_SourceUnit],
    segments: _Segments,
) -> tuple[list[_SourceUnit], int]:
    output: list[_SourceUnit] = []
    starter_index: int | None = None
    last_ccc = 0
    work_units = 0

    for unit in ordered:
        ccc = unicodedata.combining(unit.value)
        composed_value: str | None = None
        if starter_index is not None and (last_ccc < ccc or last_ccc == 0):
            starter = output[starter_index]
            # NFC is applied only to a two-code-point composition probe. This
            # preserves Unicode/Hangul composition without quadratic mark runs.
            candidate = unicodedata.normalize("NFC", starter.value + unit.value)
            work_units += 2
            if len(candidate) == 1:
                composed_value = candidate
                segment_id = segments.union(starter.segment_id, unit.segment_id)
                output[starter_index] = _SourceUnit(
                    candidate,
                    min(starter.original_start, unit.original_start),
                    max(starter.original_end, unit.original_end),
                    starter.source_unit_id,
                    segment_id,
                )

        if composed_value is not None:
            continue

        output.append(unit)
        work_units += 1
        if ccc == 0:
            starter_index = len(output) - 1
        last_ccc = ccc

    return output, work_units


def _normalize_core(text: str) -> tuple[str, dict[str, Any]]:
    units, work_units = _line_ending_units(text)
    decomposed, decomposition_work = _canonical_decompose(units)
    work_units += decomposition_work
    segment_union = _Segments()
    ordered, ordering_work = _canonical_order_and_segments(
        decomposed, segment_union
    )
    work_units += ordering_work
    composed, composition_work = _canonical_compose(ordered, segment_union)
    work_units += composition_work

    untrimmed = "".join(unit.value for unit in composed)
    trim_start = 0
    while trim_start < len(untrimmed) and untrimmed[trim_start].isspace():
        trim_start += 1
        work_units += 1
    trim_end = len(untrimmed)
    while trim_end > trim_start and untrimmed[trim_end - 1].isspace():
        trim_end -= 1
        work_units += 1

    normalized = untrimmed[trim_start:trim_end]
    retained = composed[trim_start:trim_end]
    char_map: list[list[int]] = []
    mapped_roots: list[int] = []
    for unit in retained:
        root = segment_union.find(unit.segment_id)
        mapped_roots.append(root)
        char_map.append([segment_union.start[root], segment_union.end[root]])
        work_units += 1

    mapped_segments: list[dict[str, int]] = []
    cursor = 0
    while cursor < len(retained):
        root = mapped_roots[cursor]
        end = cursor + 1
        while end < len(retained) and mapped_roots[end] == root:
            end += 1
        mapped_segments.append(
            {
                "normalizedStart": cursor,
                "normalizedEnd": end,
                "originalStart": segment_union.start[root],
                "originalEnd": segment_union.end[root],
            }
        )
        cursor = end

    metadata: dict[str, Any] = {
        "version": NORMALIZATION_VERSION,
        "coordinateSpace": "normalized_atomic",
        "originalCoordinateSpace": "original_atomic",
        "originalLength": len(text),
        "normalizedLength": len(normalized),
        "charMap": char_map,
        "segments": mapped_segments,
        "normalizationWorkUnits": work_units,
        # Retained only while orchestrating; service output exposes validated
        # source spans and never emits this transient field directly.
        "originalText": text,
    }
    return normalized, metadata


def normalize_text(text: str) -> str:
    """Apply NFC + LF + strip without whole-run normalization calls."""

    return _normalize_core(text)[0]


def normalize_text_with_map(text: str) -> tuple[str, dict[str, Any]]:
    """Normalize text and build a monotonic near-linear original span map."""

    return _normalize_core(text)


def normalized_segment_boundaries(normalization: Mapping[str, Any]) -> tuple[int, ...]:
    """Return validated legal half-open boundaries for reversible source spans."""

    normalized_length = normalization.get("normalizedLength")
    raw_segments = normalization.get("segments")
    if (
        not isinstance(normalized_length, int)
        or isinstance(normalized_length, bool)
        or normalized_length < 0
        or not isinstance(raw_segments, (tuple, list))
    ):
        raise ValueError("normalized atomic block has invalid normalization segments")
    boundaries = {0, normalized_length}
    cursor = 0
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, Mapping):
            raise ValueError("normalized atomic block has invalid normalization segments")
        start = raw_segment.get("normalizedStart")
        end = raw_segment.get("normalizedEnd")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start != cursor
            or not start < end <= normalized_length
        ):
            raise ValueError("normalized atomic block has invalid normalization segments")
        boundaries.update((start, end))
        cursor = end
    if cursor != normalized_length and normalized_length != 0:
        raise ValueError("normalized atomic block has incomplete normalization segments")
    return tuple(sorted(boundaries))


def _containing_segment(
    normalization: Mapping[str, Any], normalized_start: int, normalized_end: int
) -> Mapping[str, Any] | None:
    raw_segments = normalization.get("segments")
    if not isinstance(raw_segments, (tuple, list)):
        return None
    for segment in raw_segments:
        if not isinstance(segment, Mapping):
            continue
        start = segment.get("normalizedStart")
        end = segment.get("normalizedEnd")
        if (
            isinstance(start, int)
            and not isinstance(start, bool)
            and isinstance(end, int)
            and not isinstance(end, bool)
            and start <= normalized_start < normalized_end <= end
        ):
            return segment
    return None


def normalized_span_to_original(
    normalization: Mapping[str, Any],
    normalized_start: int,
    normalized_end: int,
    *,
    expected_normalized: str | None = None,
) -> tuple[int, int]:
    """Map a non-empty reversible normalized span to original coordinates."""

    raw_map = normalization.get("charMap")
    normalized_length = normalization.get("normalizedLength")
    if (
        not isinstance(raw_map, (tuple, list))
        or not isinstance(normalized_length, int)
        or isinstance(normalized_length, bool)
        or len(raw_map) != normalized_length
        or not 0 <= normalized_start < normalized_end <= normalized_length
    ):
        raise ValueError("normalized atomic block has an invalid character map")
    boundaries = normalized_segment_boundaries(normalization)
    if normalized_start not in boundaries or normalized_end not in boundaries:
        raise ValueError(
            "normalized span does not align to a reversible normalization segment"
        )
    start_entry = raw_map[normalized_start]
    end_entry = raw_map[normalized_end - 1]
    if not (
        isinstance(start_entry, (tuple, list))
        and len(start_entry) == 2
        and isinstance(end_entry, (tuple, list))
        and len(end_entry) == 2
    ):
        raise ValueError("normalized atomic block has an invalid character span")
    original_start = int(start_entry[0])
    original_end = int(end_entry[1])
    if original_start >= original_end:
        raise ValueError("normalized non-empty span mapped to an empty original span")

    original_text = normalization.get("originalText")
    if expected_normalized is not None:
        if not isinstance(original_text, str):
            raise ValueError("normalization map is missing its original source text")
        actual = normalize_text(original_text[original_start:original_end])
        if actual != expected_normalized:
            raise ValueError(
                "normalized span does not align to a reversible normalization segment"
            )
    return original_start, original_end


def normalized_fragment_provenance(
    normalization: Mapping[str, Any],
    normalized_start: int,
    normalized_end: int,
) -> dict[str, int | str]:
    """Describe a bounded fragment inside one indivisible normalization segment."""

    segment = _containing_segment(normalization, normalized_start, normalized_end)
    if segment is None:
        raise ValueError("normalized fragment crosses normalization segment boundaries")
    return {
        "provenanceMode": "normalization_segment_fragment",
        "coordinateSpace": "normalized_atomic_segment_fragment",
        "originalSegmentStart": int(segment["originalStart"]),
        "originalSegmentEnd": int(segment["originalEnd"]),
        "normalizedSegmentStart": int(segment["normalizedStart"]),
        "normalizedSegmentEnd": int(segment["normalizedEnd"]),
        "normalizedFragmentStart": normalized_start,
        "normalizedFragmentEnd": normalized_end,
    }


__all__ = [
    "NORMALIZATION_METADATA_KEY",
    "NORMALIZATION_VERSION",
    "normalize_text",
    "normalize_text_with_map",
    "normalized_fragment_provenance",
    "normalized_segment_boundaries",
    "normalized_span_to_original",
]
