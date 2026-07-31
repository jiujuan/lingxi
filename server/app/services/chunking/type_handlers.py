"""Pure content-type-specific chunk handlers for adaptive chunking."""

from __future__ import annotations

import hashlib
import re
from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import InitVar, dataclass, field, replace
from types import MappingProxyType
from typing import Any

from server.app.services.chunking.contracts import (
    AtomicBlock,
    BlockType,
    ChunkingWarning,
    _freeze_json_mapping,
    to_json_value,
)
from server.app.services.chunking.merge import MergedBlock
from server.app.services.chunking.policy import ChunkPolicy
from server.app.services.chunking.recursive_splitter import split_oversized_prose
from server.app.services.chunking.tokenizer import (
    TokenCounter,
    TokenLimitError,
    require_token_counter,
)

_TABLE_OVERSIZED_ROW_FALLBACK = "TABLE_OVERSIZED_ROW_FALLBACK"
_CODE_FALLBACK_SPLIT = "CODE_FALLBACK_SPLIT"
_IMAGE_WITHOUT_TEXT_SKIPPED = "IMAGE_WITHOUT_TEXT_SKIPPED"
_HANDLER_VERSION = "1.0"


@dataclass(frozen=True)
class ChunkDraft:
    """Immutable non-prose Child Chunk draft.

    Type handlers never apply generic overlap, so ``unique_content`` is exactly
    ``content``. Construction requires a TokenCounter and verifies ``token_count``;
    :func:`handle_typed_block` re-verifies the emitted draft at dispatch.
    """

    content: str
    block_type: BlockType
    title_path: tuple[str, ...] | list[str]
    token_count: int
    page_start: int | None
    page_end: int | None
    source_locators: tuple[Mapping[str, Any], ...]
    atomic_block_indexes: tuple[int, ...]
    token_counter: InitVar[TokenCounter]
    overlap_prefix_tokens: int = 0
    unique_content: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self, token_counter: TokenCounter) -> None:
        counter = require_token_counter(token_counter)
        if not isinstance(self.content, str) or not self.content:
            raise ValueError("ChunkDraft content must not be empty")
        if (
            not isinstance(self.token_count, int)
            or isinstance(self.token_count, bool)
            or self.token_count < 0
        ):
            raise ValueError("ChunkDraft token_count must be non-negative")
        if (
            not isinstance(self.overlap_prefix_tokens, int)
            or isinstance(self.overlap_prefix_tokens, bool)
            or self.overlap_prefix_tokens < 0
        ):
            raise ValueError("ChunkDraft overlap_prefix_tokens must be non-negative")
        if counter.count(self.content) != self.token_count:
            raise ValueError("ChunkDraft token_count does not match content")
        if self.overlap_prefix_tokens > self.token_count:
            raise ValueError("ChunkDraft overlap_prefix_tokens exceeds token_count")
        if self.overlap_prefix_tokens != 0:
            raise ValueError("non-prose ChunkDraft values cannot contain overlap")

        unique_content = self.content if self.unique_content is None else self.unique_content
        if not isinstance(unique_content, str) or not unique_content:
            raise ValueError("ChunkDraft unique_content must not be empty")
        if unique_content != self.content:
            raise ValueError("non-prose ChunkDraft unique_content must equal content")

        if not isinstance(self.title_path, (tuple, list)):
            raise ValueError("ChunkDraft title_path must be a tuple or list")
        title_path = tuple(self.title_path)
        if any(
            not isinstance(part, str) or not part.strip()
            for part in title_path
        ):
            raise ValueError("ChunkDraft title_path entries must be non-empty strings")

        source_locators = tuple(self.source_locators)
        if not source_locators or any(
            not isinstance(locator, Mapping) or not locator
            for locator in source_locators
        ):
            raise ValueError("ChunkDraft requires non-empty source locators")
        atomic_indexes = tuple(self.atomic_block_indexes)
        if not atomic_indexes or any(
            not isinstance(index, int) or isinstance(index, bool) or index < 0
            for index in atomic_indexes
        ):
            raise ValueError("ChunkDraft requires non-negative atomic block indexes")
        if len(set(atomic_indexes)) != len(atomic_indexes):
            raise ValueError("ChunkDraft atomic block indexes must be unique")
        if atomic_indexes != tuple(sorted(atomic_indexes)):
            raise ValueError("ChunkDraft atomic block indexes must be stably sorted")
        if len(source_locators) != len(atomic_indexes):
            raise ValueError("ChunkDraft source locators and indexes must align")

        for page_value in (self.page_start, self.page_end):
            if page_value is not None and (
                not isinstance(page_value, int)
                or isinstance(page_value, bool)
                or page_value < 0
            ):
                raise ValueError("ChunkDraft page values must be non-negative integers")
        if (self.page_start is None) != (self.page_end is None):
            raise ValueError("ChunkDraft page range must be fully specified or empty")
        if (
            self.page_start is not None
            and self.page_end is not None
            and self.page_start > self.page_end
        ):
            raise ValueError("ChunkDraft page range is invalid")

        locator_pages: list[int] = []
        for locator, atomic_index in zip(source_locators, atomic_indexes, strict=True):
            if "block" in locator:
                locator_block = locator["block"]
                if not isinstance(locator_block, int) or isinstance(locator_block, bool):
                    raise ValueError(
                        "ChunkDraft locator block provenance must be an integer"
                    )
                if locator_block != atomic_index:
                    raise ValueError(
                        "ChunkDraft locator block does not match atomic index"
                    )
            if "page" in locator:
                locator_page = locator["page"]
                if not isinstance(locator_page, int) or isinstance(locator_page, bool):
                    raise ValueError(
                        "ChunkDraft locator page provenance must be an integer"
                    )
                if locator_page < 0:
                    raise ValueError("ChunkDraft locator page must be non-negative")
                locator_pages.append(locator_page)
        if locator_pages and (
            self.page_start is None
            or self.page_end is None
            or min(locator_pages) != self.page_start
            or max(locator_pages) != self.page_end
        ):
            raise ValueError("ChunkDraft locator page provenance does not match page range")

        frozen_locators = tuple(
            _freeze_json_mapping(locator, field_name="ChunkDraft source locator")
            for locator in source_locators
        )

        frozen_metadata = _freeze_json_mapping(
            self.metadata, field_name="ChunkDraft metadata"
        )
        if "overlap" in frozen_metadata:
            raise ValueError("non-prose ChunkDraft metadata cannot contain overlap")

        object.__setattr__(self, "block_type", BlockType(self.block_type))
        object.__setattr__(self, "title_path", title_path)
        object.__setattr__(self, "source_locators", frozen_locators)
        object.__setattr__(self, "atomic_block_indexes", atomic_indexes)
        object.__setattr__(self, "unique_content", unique_content)
        object.__setattr__(self, "metadata", frozen_metadata)


@dataclass(frozen=True)
class TypeHandlerContext:
    """Strict adjacent atomic context supplied by orchestration.

    When neighbors are present, ``source_identity`` and ``current_position``
    make document membership and adjacency explicit instead of inferring them
    from page/title values that can collide across documents.
    """

    previous: AtomicBlock | None = None
    following: AtomicBlock | None = None
    source_identity: str | None = None
    current_position: int | None = None
    previous_position: int | None = None
    following_position: int | None = None

    def __post_init__(self) -> None:
        if self.previous is not None and not isinstance(self.previous, AtomicBlock):
            raise ValueError("previous context must be an AtomicBlock")
        if self.following is not None and not isinstance(self.following, AtomicBlock):
            raise ValueError("following context must be an AtomicBlock")

        positions = {
            "current": self.current_position,
            "previous": self.previous_position,
            "following": self.following_position,
        }
        for name, position in positions.items():
            if position is not None and (
                not isinstance(position, int)
                or isinstance(position, bool)
                or position < 0
            ):
                raise ValueError(f"context {name} position must be non-negative")

        has_neighbors = self.previous is not None or self.following is not None
        if has_neighbors:
            if not isinstance(self.source_identity, str) or not self.source_identity.strip():
                raise ValueError("neighbor context requires a stable source identity")
            if self.current_position is None:
                raise ValueError("neighbor context requires a current position")
            if self.previous is not None and self.previous_position is None:
                raise ValueError("previous context requires a sequence position")
            if self.following is not None and self.following_position is None:
                raise ValueError("following context requires a sequence position")
        elif self.source_identity is not None or self.current_position is not None:
            if not isinstance(self.source_identity, str) or not self.source_identity.strip():
                raise ValueError("context source identity must be non-empty")
            if self.current_position is None:
                raise ValueError("context current position must be non-negative")

        if self.previous is None and self.previous_position is not None:
            raise ValueError("previous position requires a previous block")
        if self.following is None and self.following_position is not None:
            raise ValueError("following position requires a following block")


@dataclass(frozen=True)
class TypeHandlerResult:
    """Immutable drafts and warnings returned by every type handler."""

    drafts: tuple[ChunkDraft, ...] = ()
    warnings: tuple[ChunkingWarning, ...] = ()

    def __post_init__(self) -> None:
        drafts = tuple(self.drafts)
        warnings = tuple(self.warnings)
        if any(not isinstance(draft, ChunkDraft) for draft in drafts):
            raise ValueError("TypeHandlerResult drafts must be ChunkDraft values")
        if any(not isinstance(warning, ChunkingWarning) for warning in warnings):
            raise ValueError("TypeHandlerResult warnings must be ChunkingWarning values")
        object.__setattr__(self, "drafts", drafts)
        object.__setattr__(self, "warnings", warnings)


@dataclass(frozen=True)
class _CodePart:
    content: str
    reason: str
    line_start: int | None
    line_end: int | None
    source_char_start: int
    source_char_end: int
    lexical_degraded: bool = False
    prefix_degraded: bool = False


@dataclass(frozen=True)
class _CodeSegment:
    start: int
    end: int
    reason: str
    signature: str | None = None


def _plain_metadata(block: AtomicBlock) -> dict[str, Any]:
    return to_json_value(block.metadata)


def _source_locator(block: AtomicBlock) -> dict[str, Any]:
    return to_json_value(block.source_locator)


def _non_empty_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _dedupe_texts(values: Sequence[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        normalized = " ".join(value.split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def _draft(
    block: AtomicBlock,
    content: str,
    counter: TokenCounter,
    metadata: Mapping[str, Any],
    *,
    source_blocks: Sequence[AtomicBlock] | None = None,
) -> ChunkDraft:
    candidates = (block,) if source_blocks is None else tuple(source_blocks)
    if not candidates:
        raise ValueError("ChunkDraft provenance requires at least one source block")
    by_index: dict[int, AtomicBlock] = {}
    for candidate in candidates:
        existing = by_index.get(candidate.index)
        if existing is not None and existing != candidate:
            raise ValueError("source blocks must have unique stable indexes")
        by_index[candidate.index] = candidate
    ordered_sources = tuple(by_index[index] for index in sorted(by_index))
    pages = [source.page_no for source in ordered_sources if source.page_no is not None]
    return ChunkDraft(
        content=content,
        unique_content=content,
        block_type=block.block_type,
        title_path=block.title_path,
        token_count=counter.count(content),
        page_start=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
        source_locators=tuple(source.source_locator for source in ordered_sources),
        atomic_block_indexes=tuple(source.index for source in ordered_sources),
        token_counter=counter,
        overlap_prefix_tokens=0,
        metadata=metadata,
    )


def _hard_split_exact(
    text: str,
    limit: int,
    counter: TokenCounter,
) -> list[str]:
    """Split exactly with logarithmic boundary probes and Unicode-safe indexes."""

    if not text:
        return []
    if limit <= 0:
        raise ValueError("token limit must be positive")
    if counter.count(text) <= limit:
        return [text]

    delegated = counter.split_by_token_limit(text, limit)
    if (
        delegated
        and "".join(delegated) == text
        and all(part and counter.count(part) <= limit for part in delegated)
    ):
        return delegated

    parts: list[str] = []
    start = 0
    while start < len(text):
        low = start + 1
        high = len(text)
        if counter.count(text[start:low]) > limit:
            raise ValueError("one Unicode code point exceeds the token budget")
        best = low
        while low <= high:
            middle = low + ((high - low) // 2)
            if counter.count(text[start:middle]) <= limit:
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        part = text[start:best]
        if not part:
            raise ValueError("exact token fallback failed to make progress")
        parts.append(part)
        start = best
    if "".join(parts) != text:
        raise ValueError("exact token fallback did not preserve source text")
    return parts


def _safe_token_parts(
    text: str,
    limit: int,
    counter: TokenCounter,
) -> list[str]:
    parts = _hard_split_exact(text, limit, counter)
    if not parts or any(not part or counter.count(part) > limit for part in parts):
        raise ValueError("token counter failed to produce bounded non-empty parts")
    return parts


def _candidate_token_parts(
    text: str,
    limit: int,
    counter: TokenCounter,
) -> list[str] | None:
    """Return bounded parts, or None when only this candidate limit is impossible."""

    try:
        return _safe_token_parts(text, limit, counter)
    except TokenLimitError:
        return None


def _bounded_candidate_limits(initial: int) -> tuple[int, ...]:
    if initial <= 0:
        return ()
    candidates = list(range(initial, max(0, initial - 8), -1))
    current = max(1, initial - 8)
    while current > 1:
        candidates.append(current)
        current = max(1, current // 2)
    candidates.append(1)
    return tuple(dict.fromkeys(candidates))


@dataclass(frozen=True)
class _PrefixPlan:
    repeated: str
    standalone_parts: tuple[str, ...]
    degraded: bool


def _prepare_repeated_prefix(
    prefix: str,
    max_tokens: int,
    counter: TokenCounter,
    *,
    separator: str = "\n",
) -> _PrefixPlan:
    normalized = prefix.rstrip()
    if not normalized:
        return _PrefixPlan("", (), False)
    if counter.count(f"{normalized}{separator}x") <= max_tokens:
        return _PrefixPlan(normalized, (), False)
    return _PrefixPlan(
        "",
        tuple(_safe_token_parts(normalized, max_tokens, counter)),
        True,
    )


def _split_with_repeated_prefix(
    prefix: str,
    body: str,
    max_tokens: int,
    counter: TokenCounter,
    *,
    separator: str = "\n",
) -> list[str]:
    """Bounded split that degrades an impossible prefix to standalone parts."""

    body = body.strip()
    plan = _prepare_repeated_prefix(prefix, max_tokens, counter, separator=separator)
    if not body:
        return list(plan.standalone_parts or ((plan.repeated,) if plan.repeated else ()))
    if not plan.repeated:
        return [*plan.standalone_parts, *_safe_token_parts(body, max_tokens, counter)]

    full = f"{plan.repeated}{separator}{body}"
    if counter.count(full) <= max_tokens:
        return [full]
    initial_limit = max(1, max_tokens - counter.count(plan.repeated))
    for body_limit in _bounded_candidate_limits(initial_limit):
        body_parts = _candidate_token_parts(body, body_limit, counter)
        if body_parts is None:
            continue
        rendered = [f"{plan.repeated}{separator}{part}" for part in body_parts]
        if all(counter.count(part) <= max_tokens for part in rendered):
            return rendered
    return [*plan.standalone_parts, *_safe_token_parts(body, max_tokens, counter)]


def _pack_units(
    units: Sequence[str],
    prefix: str,
    max_tokens: int,
    counter: TokenCounter,
    *,
    separator: str = "\n",
) -> list[tuple[str, int, int, bool]]:
    """Pack units and explicitly mark fragments that cannot retain a prefix."""

    plan = _prepare_repeated_prefix(prefix, max_tokens, counter, separator=separator)
    active_prefix = plan.repeated
    packed: list[tuple[str, int, int, bool]] = []
    buffer: list[str] = []
    start = 0

    def render(values: Sequence[str]) -> str:
        body = separator.join(values)
        return f"{active_prefix}{separator}{body}" if active_prefix else body

    for index, unit in enumerate(units):
        candidate = [*buffer, unit]
        if counter.count(render(candidate)) <= max_tokens:
            if not buffer:
                start = index
            buffer = candidate
            continue
        if buffer:
            packed.append((render(buffer), start, index - 1, False))
            buffer = []
        if counter.count(render([unit])) <= max_tokens:
            start = index
            buffer = [unit]
            continue

        prefixed_parts: list[str] | None = None
        if active_prefix:
            for body_limit in _bounded_candidate_limits(max_tokens):
                body_parts = _candidate_token_parts(unit, body_limit, counter)
                if body_parts is None:
                    continue
                rendered_parts = [
                    f"{active_prefix}{separator}{part}" for part in body_parts
                ]
                if all(counter.count(part) <= max_tokens for part in rendered_parts):
                    prefixed_parts = rendered_parts
                    break
        if prefixed_parts is not None:
            packed.extend(
                (rendered_part, index, index, False)
                for rendered_part in prefixed_parts
            )
            continue

        for part in _safe_token_parts(unit, max_tokens, counter):
            packed.append((part, index, index, bool(active_prefix)))
    if buffer:
        packed.append((render(buffer), start, len(units) - 1, False))
    return packed


def _render_table_header(header: Any) -> tuple[str, list[str] | None]:
    if isinstance(header, str) and header.strip():
        return header.strip(), None
    if isinstance(header, (list, tuple)) and header:
        cells = [str(cell).strip() for cell in header]
        header_text = "\n".join(
            (
                "| " + " | ".join(cells) + " |",
                "| " + " | ".join("---" for _ in cells) + " |",
            )
        )
        return header_text, cells
    return "", None


def _render_table_row(row: Any) -> tuple[str, list[str] | None]:
    if isinstance(row, str):
        return row.strip(), _parse_markdown_cells(row)
    if isinstance(row, (list, tuple)):
        cells = [str(cell).strip() for cell in row]
        return "| " + " | ".join(cells) + " |", cells
    return str(row).strip(), None


def _parse_markdown_cells(row: str) -> list[str] | None:
    stripped = row.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _split_table_column_groups(
    caption: str,
    header_cells: list[str] | None,
    row_cells: list[str] | None,
    max_tokens: int,
    counter: TokenCounter,
) -> list[tuple[str, int, int, str]] | None:
    if (
        header_cells is None
        or row_cells is None
        or len(header_cells) != len(row_cells)
        or len(header_cells) < 2
    ):
        return None

    def render(start: int, end: int) -> tuple[str, str]:
        header_text, _ = _render_table_header(header_cells[start:end])
        row_text, _ = _render_table_row(row_cells[start:end])
        prefix = "\n".join(value for value in (caption, header_text) if value)
        return f"{prefix}\n{row_text}", header_text

    if any(
        counter.count(render(index, index + 1)[0]) > max_tokens
        for index in range(len(header_cells))
    ):
        return None

    groups: list[tuple[str, int, int, str]] = []
    start = 0
    while start < len(header_cells):
        end = start + 1
        content, group_header = render(start, end)
        while end < len(header_cells):
            candidate, candidate_header = render(start, end + 1)
            if counter.count(candidate) > max_tokens:
                break
            end += 1
            content, group_header = candidate, candidate_header
        groups.append((content, start + 1, end, group_header))
        start = end
    return groups if len(groups) > 1 else None


def _table_parts_from_content(content: str) -> tuple[str, list[str]]:
    lines = [line.rstrip() for line in content.strip().splitlines() if line.strip()]
    if len(lines) >= 2 and re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", lines[1]):
        return "\n".join(lines[:2]), lines[2:]
    if lines:
        return lines[0], lines[1:]
    return "", []


def _table_metadata(
    *,
    row_start: int,
    row_end: int,
    header_hash: str,
    repeated_header_tokens: int,
    split_reason: str,
    part_index: int | None = None,
    part_count: int | None = None,
) -> dict[str, Any]:
    table: dict[str, Any] = {
        "rowStart": row_start,
        "rowEnd": row_end,
        "headerHash": header_hash,
        "repeatedHeaderTokens": repeated_header_tokens,
        "splitReason": split_reason,
    }
    if part_index is not None:
        table["partIndex"] = part_index
    if part_count is not None:
        table["partCount"] = part_count
    return {"handlerVersion": _HANDLER_VERSION, "table": table}


def _limited_policy(policy: ChunkPolicy, max_tokens: int) -> ChunkPolicy:
    limit = max(1, max_tokens)
    return replace(
        policy,
        min_tokens=1,
        target_tokens=max(1, min(policy.target_tokens, limit)),
        max_tokens=limit,
        overlap_tokens=0,
        parent_max_tokens=max(policy.parent_max_tokens, limit),
        embedding_provider_input_limit=max(
            policy.embedding_provider_input_limit, limit
        ),
    )


def _recursive_text_parts(
    text: str,
    block: AtomicBlock,
    policy: ChunkPolicy,
    counter: TokenCounter,
    max_tokens: int,
) -> list[str]:
    if counter.count(text) <= max_tokens:
        return [text]
    temporary = AtomicBlock(
        index=block.index,
        content=text,
        block_type=BlockType.TEXT,
        source_locator=block.source_locator,
        page_no=block.page_no,
        title_path=block.title_path,
        structural_id=block.structural_id,
        parent_structural_id=block.parent_structural_id,
        metadata={},
    )
    merged = MergedBlock(
        content=text,
        block_type=BlockType.TEXT,
        title_path=block.title_path,
        token_count=counter.count(text),
        page_start=block.page_no,
        page_end=block.page_no,
        source_locators=(block.source_locator,),
        atomic_block_indexes=(block.index,),
        atomic_blocks=(temporary,),
    )
    result = split_oversized_prose(
        merged,
        _limited_policy(policy, max_tokens),
        counter,
    )
    return [candidate.content for candidate in result.blocks]


def _handle_table(
    block: AtomicBlock,
    policy: ChunkPolicy,
    counter: TokenCounter,
    context: TypeHandlerContext,
) -> TypeHandlerResult:
    del context
    metadata = _plain_metadata(block)
    locator = _source_locator(block)
    caption = _non_empty_text(metadata.get("caption")) or ""
    header_text, header_cells = _render_table_header(metadata.get("header"))
    raw_rows = metadata.get("rows")
    rows: list[str]
    row_cells: list[list[str] | None]
    if isinstance(raw_rows, (list, tuple)):
        rendered_rows = [_render_table_row(row) for row in raw_rows]
        rows = [rendered[0] for rendered in rendered_rows]
        row_cells = [rendered[1] for rendered in rendered_rows]
    else:
        parsed_header, rows = _table_parts_from_content(block.content)
        if not header_text:
            header_text = parsed_header
            header_cells = _parse_markdown_cells(parsed_header.splitlines()[0])
        row_cells = [_parse_markdown_cells(row) for row in rows]
    non_empty_rows = [
        (row, cells) for row, cells in zip(rows, row_cells, strict=True) if row
    ]
    rows = [row for row, _ in non_empty_rows]
    row_cells = [cells for _, cells in non_empty_rows]
    if not header_text:
        header_text = "Table"

    prefix = "\n".join(value for value in (caption, header_text) if value)
    prefix_plan = _prepare_repeated_prefix(prefix, policy.max_tokens, counter)
    column_context_possible = bool(
        header_cells
        and len(header_cells) > 1
        and all(
            counter.count(
                "\n".join(
                    value
                    for value in (
                        caption,
                        _render_table_header([header_cell])[0],
                        "x",
                    )
                    if value
                )
            )
            <= policy.max_tokens
            for header_cell in header_cells
        )
    )
    if prefix_plan.degraded and column_context_possible:
        # A wide full header is not an oversized context: column grouping owns it.
        prefix_plan = _PrefixPlan(prefix, (), False)
    active_prefix = prefix_plan.repeated
    header_hash = hashlib.sha256(header_text.encode("utf-8")).hexdigest()
    repeated_header_tokens = counter.count(header_text)
    raw_row_start = metadata.get("rowStart", locator.get("rowStart", 1))
    row_start = (
        raw_row_start
        if isinstance(raw_row_start, int) and not isinstance(raw_row_start, bool)
        else 1
    )

    drafts: list[ChunkDraft] = []
    warnings: list[ChunkingWarning] = []
    degradations: list[str] = []

    def record_degradation(value: str) -> None:
        if value not in degradations:
            degradations.append(value)

    if prefix_plan.degraded:
        record_degradation("context_standalone")
        degradation = "context_standalone"
        for index, part in enumerate(prefix_plan.standalone_parts, 1):
            context_metadata = _table_metadata(
                row_start=row_start,
                row_end=row_start,
                header_hash=header_hash,
                repeated_header_tokens=0,
                split_reason="context_fallback",
                part_index=index,
                part_count=len(prefix_plan.standalone_parts),
            )
            context_metadata["table"]["contextDegraded"] = True
            context_metadata["table"]["degradation"] = degradation
            drafts.append(_draft(block, part, counter, context_metadata))

    if not rows:
        if not drafts:
            for index, part in enumerate(
                _safe_token_parts(prefix or block.content, policy.max_tokens, counter), 1
            ):
                drafts.append(
                    _draft(
                        block,
                        part,
                        counter,
                        _table_metadata(
                            row_start=row_start,
                            row_end=row_start,
                            header_hash=header_hash,
                            repeated_header_tokens=(
                                repeated_header_tokens if active_prefix else 0
                            ),
                            split_reason="header_only",
                            part_index=index,
                            part_count=None,
                        ),
                    )
                )
        if degradations:
            warnings.append(
                ChunkingWarning(
                    code=_TABLE_OVERSIZED_ROW_FALLBACK,
                    message="table context exceeded the repeated-prefix budget",
                    metadata={
                        "atomicBlockIndex": block.index,
                        "stage": "context",
                        "stages": ["context"],
                        "degradation": degradations[-1],
                    },
                )
            )
        return TypeHandlerResult(tuple(drafts), tuple(warnings))

    buffer: list[str] = []
    buffer_start = 0

    def render_rows(values: Sequence[str]) -> str:
        body = "\n".join(values)
        return f"{active_prefix}\n{body}" if active_prefix else body

    def flush(end_index: int) -> None:
        nonlocal buffer, buffer_start
        if not buffer:
            return
        table_metadata = _table_metadata(
            row_start=row_start + buffer_start,
            row_end=row_start + end_index,
            header_hash=header_hash,
            repeated_header_tokens=(repeated_header_tokens if active_prefix else 0),
            split_reason="row_group",
        )
        if prefix_plan.degraded:
            table_metadata["table"]["contextDegraded"] = True
            table_metadata["table"]["degradation"] = "context_standalone"
        drafts.append(_draft(block, render_rows(buffer), counter, table_metadata))
        buffer = []

    for row_index, row in enumerate(rows):
        cells_for_row = row_cells[row_index]
        all_empty_structured = bool(cells_for_row) and not any(
            cell.strip() for cell in cells_for_row or ()
        )
        candidate_rows = [*buffer, row]
        if (
            not all_empty_structured
            and counter.count(render_rows(candidate_rows)) <= policy.max_tokens
        ):
            if not buffer:
                buffer_start = row_index
            buffer = candidate_rows
            continue

        flush(row_index - 1)
        if (
            not all_empty_structured
            and counter.count(render_rows([row])) <= policy.max_tokens
        ):
            buffer_start = row_index
            buffer = [row]
            continue

        # Deterministic stage 1: structured column groups.
        column_groups = None if all_empty_structured else _split_table_column_groups(
            caption if active_prefix else "",
            header_cells,
            row_cells[row_index],
            policy.max_tokens,
            counter,
        )
        if column_groups is not None:
            for content, column_start, column_end, group_header in column_groups:
                group_metadata = _table_metadata(
                    row_start=row_start + row_index,
                    row_end=row_start + row_index,
                    header_hash=hashlib.sha256(group_header.encode("utf-8")).hexdigest(),
                    repeated_header_tokens=counter.count(group_header),
                    split_reason="column_group",
                )
                group_metadata["table"].update(
                    {
                        "columnStart": column_start,
                        "columnEnd": column_end,
                        "sourceHeaderHash": header_hash,
                    }
                )
                drafts.append(_draft(block, content, counter, group_metadata))
            continue

        # Deterministic stage 2: recursively split each structured cell.
        cells = row_cells[row_index]
        if (
            cells is not None
            and header_cells is not None
            and len(cells) == len(header_cells)
            and cells
        ):
            valid_cells = [
                (column_index, cell)
                for column_index, cell in enumerate(cells)
                if cell.strip()
            ]
            pending_cell_drafts: list[ChunkDraft] = []
            all_cells_preserved = bool(valid_cells)
            for column_index, cell in valid_cells:
                cell_header, _ = _render_table_header([header_cells[column_index]])
                cell_prefix = "\n".join(
                    value
                    for value in (caption if active_prefix else "", cell_header)
                    if value
                )
                cell_plan = _prepare_repeated_prefix(
                    cell_prefix, policy.max_tokens, counter
                )
                body_limit = policy.max_tokens
                if cell_plan.repeated:
                    body_limit = max(
                        1,
                        policy.max_tokens - counter.count(cell_plan.repeated) - 1,
                    )
                cell_parts = _recursive_text_parts(
                    cell, block, policy, counter, body_limit
                )
                if not cell_parts or "".join(cell_parts) != cell:
                    cell_parts = _safe_token_parts(cell, body_limit, counter)
                if not cell_parts or "".join(cell_parts) != cell:
                    all_cells_preserved = False
                    break
                emitted_for_cell: list[ChunkDraft] = []
                for part_index, cell_part in enumerate(cell_parts, 1):
                    rendered = (
                        f"{cell_plan.repeated}\n{cell_part}"
                        if cell_plan.repeated
                        else cell_part
                    )
                    rendered_parts = (
                        [rendered]
                        if counter.count(rendered) <= policy.max_tokens
                        else _safe_token_parts(cell_part, policy.max_tokens, counter)
                    )
                    for rendered_part in rendered_parts:
                        if not rendered_part:
                            continue
                        cell_metadata = _table_metadata(
                            row_start=row_start + row_index,
                            row_end=row_start + row_index,
                            header_hash=header_hash,
                            repeated_header_tokens=(
                                counter.count(cell_header)
                                if cell_plan.repeated
                                else 0
                            ),
                            split_reason="cell_recursive",
                            part_index=part_index,
                            part_count=len(cell_parts),
                        )
                        cell_metadata["table"].update(
                            {
                                "columnStart": column_index + 1,
                                "columnEnd": column_index + 1,
                                "sourceHeaderHash": header_hash,
                                "contextDegraded": True,
                                "degradation": "cell_recursive",
                                "cellSourceText": cell_part,
                                "prefixDegraded": cell_plan.degraded,
                            }
                        )
                        emitted_for_cell.append(
                            _draft(block, rendered_part, counter, cell_metadata)
                        )
                if not emitted_for_cell:
                    all_cells_preserved = False
                    break
                pending_cell_drafts.extend(emitted_for_cell)
            if all_cells_preserved:
                drafts.extend(pending_cell_drafts)
                record_degradation("cell_recursive")
                continue

        # Deterministic stage 3: explicit, source-preserving token fallback.
        fallback_parts = _safe_token_parts(row, policy.max_tokens, counter)
        for part_index, part in enumerate(fallback_parts, 1):
            fallback_metadata = _table_metadata(
                row_start=row_start + row_index,
                row_end=row_start + row_index,
                header_hash=header_hash,
                repeated_header_tokens=0,
                split_reason="oversized_row_fallback",
                part_index=part_index,
                part_count=len(fallback_parts),
            )
            fallback_metadata["table"].update(
                {
                    "contextDegraded": True,
                    "degradation": "explicit_token_fallback",
                }
            )
            drafts.append(_draft(block, part, counter, fallback_metadata))
        record_degradation("explicit_token_fallback")

    flush(len(rows) - 1)
    if degradations:
        warnings.append(
            ChunkingWarning(
                code=_TABLE_OVERSIZED_ROW_FALLBACK,
                message="table required bounded context/cell/fallback degradation",
                metadata={
                    "atomicBlockIndex": block.index,
                    "stage": (
                        "explicit_fallback"
                        if "explicit_token_fallback" in degradations
                        else "cell_recursive"
                        if "cell_recursive" in degradations
                        else "context"
                    ),
                    "stages": [
                        stage
                        for stage, degradation_name in (
                            ("context", "context_standalone"),
                            ("cell_recursive", "cell_recursive"),
                            ("explicit_fallback", "explicit_token_fallback"),
                        )
                        if degradation_name in degradations
                    ],
                    "degradation": degradations[-1],
                    "degradations": degradations,
                    "partCount": len(drafts),
                },
            )
        )
    return TypeHandlerResult(drafts=tuple(drafts), warnings=tuple(warnings))


def _line_starts(content: str) -> tuple[int, ...]:
    starts = [0]
    for match in re.finditer(r"\n", content):
        if match.end() < len(content):
            starts.append(match.end())
    return tuple(starts)


def _line_range(
    starts: Sequence[int], start: int, end: int
) -> tuple[int, int]:
    first = bisect_right(starts, start)
    last_position = start if end <= start else end - 1
    last = bisect_right(starts, last_position)
    return max(1, first), max(1, last)


def _normal_lexical_units(
    content: str, start: int, end: int
) -> list[tuple[int, int, bool]]:
    units: list[tuple[int, int, bool]] = []
    cursor = start
    while cursor < end:
        newline = content.find("\n", cursor, end)
        unit_end = end if newline < 0 else newline + 1
        units.append((cursor, unit_end, False))
        cursor = unit_end
    return units


def _is_escaped(content: str, position: int, lower_bound: int) -> bool:
    backslashes = 0
    cursor = position - 1
    while cursor >= lower_bound and content[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _find_quoted_end(
    content: str,
    quote_start: int,
    quote: str,
    end: int,
) -> int:
    cursor = quote_start + len(quote)
    while cursor < end:
        candidate = content.find(quote, cursor, end)
        if candidate < 0:
            return end
        if not _is_escaped(content, candidate, quote_start + len(quote)):
            return candidate + len(quote)
        cursor = candidate + 1
    return end


def _string_opener(
    content: str, cursor: int, end: int
) -> tuple[int, str] | None:
    """Return quote position and delimiter for Python/JS-like strings."""

    quote_position = cursor
    if content[cursor] not in {"'", '"', "`"}:
        if cursor > 0 and (content[cursor - 1].isalnum() or content[cursor - 1] == "_"):
            return None
        prefix_end = cursor
        while (
            prefix_end < end
            and prefix_end - cursor < 4
            and content[prefix_end] in "rRbBuUfF"
        ):
            prefix_end += 1
        if prefix_end == cursor or prefix_end >= end:
            return None
        if content[prefix_end] not in {"'", '"'}:
            return None
        quote_position = prefix_end
    quote_char = content[quote_position]
    if quote_char == "`":
        return quote_position, "`"
    triple = quote_char * 3
    if content.startswith(triple, quote_position, end):
        return quote_position, triple
    return quote_position, quote_char


def _lexical_units(
    content: str, start: int, end: int
) -> list[tuple[int, int, bool]]:
    """Scan code once and expose only line or protected lexical boundaries.

    Protected units include ordinary/triple/raw/f strings, template literals,
    line comments, and block comments. Unclosed units extend to the source end.
    """

    units: list[tuple[int, int, bool]] = []
    cursor = start
    normal_start = start

    def emit_protected(protected_start: int, protected_end: int) -> None:
        nonlocal normal_start
        if normal_start < protected_start:
            units.extend(
                _normal_lexical_units(content, normal_start, protected_start)
            )
        units.append((protected_start, protected_end, True))
        normal_start = protected_end

    while cursor < end:
        if content.startswith("/*", cursor, end):
            close_at = content.find("*/", cursor + 2, end)
            protected_end = end if close_at < 0 else close_at + 2
            emit_protected(cursor, protected_end)
            cursor = protected_end
            continue
        if content.startswith("//", cursor, end) or content[cursor] == "#":
            newline = content.find("\n", cursor, end)
            protected_end = end if newline < 0 else newline + 1
            emit_protected(cursor, protected_end)
            cursor = protected_end
            continue

        opener = _string_opener(content, cursor, end)
        if opener is None:
            cursor += 1
            continue
        quote_position, quote = opener
        protected_end = _find_quoted_end(content, quote_position, quote, end)
        emit_protected(cursor, protected_end)
        cursor = protected_end

    if normal_start < end:
        units.extend(_normal_lexical_units(content, normal_start, end))
    return units or [(start, end, False)]

def _line_fallback_parts(
    content: str,
    max_tokens: int,
    counter: TokenCounter,
    *,
    source_start: int = 0,
    source_text: str | None = None,
    default_reason: str = "line",
) -> list[_CodePart]:
    """Preserve every character while preferring lines and lexical spans."""

    original = content if source_text is None else source_text
    starts = _line_starts(original)
    span_end = source_start + len(content)
    units = _lexical_units(original, source_start, span_end)
    parts: list[_CodePart] = []
    buffer_start: int | None = None
    buffer_end: int | None = None

    def append_part(
        part_start: int,
        part_end: int,
        reason: str,
        *,
        lexical_degraded: bool = False,
    ) -> None:
        line_start, line_end = _line_range(starts, part_start, part_end)
        parts.append(
            _CodePart(
                original[part_start:part_end],
                reason,
                line_start,
                line_end,
                part_start,
                part_end,
                lexical_degraded=lexical_degraded,
            )
        )

    def flush() -> None:
        nonlocal buffer_start, buffer_end
        if buffer_start is not None and buffer_end is not None:
            append_part(buffer_start, buffer_end, default_reason)
        buffer_start = buffer_end = None

    for unit_start, unit_end, protected in units:
        candidate_start = unit_start if buffer_start is None else buffer_start
        if counter.count(original[candidate_start:unit_end]) <= max_tokens:
            if buffer_start is None:
                buffer_start = unit_start
            buffer_end = unit_end
            continue
        flush()
        unit_text = original[unit_start:unit_end]
        if counter.count(unit_text) <= max_tokens:
            buffer_start, buffer_end = unit_start, unit_end
            continue
        cursor = unit_start
        for exact_part in _safe_token_parts(unit_text, max_tokens, counter):
            part_end = cursor + len(exact_part)
            append_part(
                cursor,
                part_end,
                "token",
                lexical_degraded=protected,
            )
            cursor = part_end
    flush()
    if "".join(part.content for part in parts) != content:
        raise ValueError("code fallback did not preserve source text")
    return parts


def _code_metadata(
    metadata: Mapping[str, Any],
    part: _CodePart,
    *,
    signature: str | None,
) -> dict[str, Any]:
    code: dict[str, Any] = {
        "language": _non_empty_text(metadata.get("language")) or "unknown",
        "file": _non_empty_text(metadata.get("file")),
        "symbolSignature": signature,
        "lineStart": part.line_start,
        "lineEnd": part.line_end,
        "sourceCharStart": part.source_char_start,
        "sourceCharEnd": part.source_char_end,
        "splitReason": part.reason,
        "lexicalDegraded": part.lexical_degraded,
        "prefixDegraded": part.prefix_degraded,
    }
    return {"handlerVersion": _HANDLER_VERSION, "code": code}


def _validated_symbol_segments(
    content: str,
    raw_symbols: Any,
) -> tuple[list[_CodeSegment], int, int]:
    if raw_symbols is None:
        return [], 0, 0
    if not isinstance(raw_symbols, (list, tuple)):
        return [], 0, 1 if raw_symbols else 0
    lines = content.splitlines(keepends=True)
    if not lines:
        lines = [content]
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    valid: list[_CodeSegment] = []
    invalid_count = 0
    malformed_metadata_count = 0
    for raw_symbol in raw_symbols:
        if not isinstance(raw_symbol, Mapping):
            invalid_count += 1
            continue
        symbol = to_json_value(raw_symbol)
        line_start = symbol.get("lineStart")
        line_end = symbol.get("lineEnd")
        if (
            not isinstance(line_start, int)
            or isinstance(line_start, bool)
            or not isinstance(line_end, int)
            or isinstance(line_end, bool)
            or line_start < 1
            or line_end < line_start
            or line_end > len(lines)
        ):
            invalid_count += 1
            continue
        start = offsets[line_start - 1]
        end = offsets[line_end]
        source = content[start:end]
        supplied_content = _non_empty_text(symbol.get("content"))
        if supplied_content is not None and supplied_content.strip() != source.strip():
            malformed_metadata_count += 1
        valid.append(
            _CodeSegment(
                start,
                end,
                "symbol",
                _non_empty_text(symbol.get("signature")),
            )
        )
    valid.sort(key=lambda segment: (segment.start, segment.end))
    non_overlapping: list[_CodeSegment] = []
    cursor = -1
    for segment in valid:
        if segment.start < cursor:
            invalid_count += 1
            continue
        non_overlapping.append(segment)
        cursor = segment.end
    return non_overlapping, invalid_count, malformed_metadata_count


def _complete_segments(
    content: str,
    structural: Sequence[_CodeSegment],
    *,
    structural_reason: str,
) -> tuple[list[_CodeSegment], int]:
    segments: list[_CodeSegment] = []
    cursor = 0
    gap_count = 0
    for segment in structural:
        if cursor < segment.start:
            segments.append(_CodeSegment(cursor, segment.start, "symbol_gap"))
            if content[cursor:segment.start].strip():
                gap_count += 1
        segments.append(
            _CodeSegment(
                segment.start,
                segment.end,
                structural_reason,
                segment.signature,
            )
        )
        cursor = segment.end
    if cursor < len(content):
        segments.append(_CodeSegment(cursor, len(content), "symbol_gap"))
        if content[cursor:].strip():
            gap_count += 1

    normalized: list[_CodeSegment] = []
    for segment in segments:
        if content[segment.start:segment.end].strip() or not normalized:
            normalized.append(segment)
            continue
        previous = normalized[-1]
        normalized[-1] = _CodeSegment(
            previous.start,
            segment.end,
            previous.reason,
            previous.signature,
        )
    return normalized, gap_count


def _fence_segments(content: str) -> list[_CodeSegment]:
    pattern = re.compile(
        r"^```[^\r\n]*(?:\r?\n).*?^```[ \t]*(?:\r?\n|$)",
        re.MULTILINE | re.DOTALL,
    )
    return [
        _CodeSegment(match.start(), match.end(), "fence")
        for match in pattern.finditer(content)
    ]


def _split_fenced_segment(
    content: str,
    segment: _CodeSegment,
    max_tokens: int,
    counter: TokenCounter,
) -> list[_CodePart]:
    source = content[segment.start:segment.end]
    first_newline = source.find("\n")
    closing_matches = list(re.finditer(r"^```[ \t]*(?:\r?\n|$)", source, re.MULTILINE))
    closing_match = closing_matches[-1] if closing_matches else None
    if first_newline < 0 or closing_match is None or closing_match.start() == 0:
        return _line_fallback_parts(
            source,
            max_tokens,
            counter,
            source_start=segment.start,
            source_text=content,
            default_reason="token",
        )
    opening = source[: first_newline + 1]
    closing_start = closing_match.start()
    closing = source[closing_start:]
    body_start = segment.start + len(opening)
    body_end = segment.start + closing_start
    marker_probe = f"{opening.rstrip()}\nx\n{closing.strip()}"
    if counter.count(marker_probe) > max_tokens:
        return [
            replace(part, prefix_degraded=True)
            for part in _line_fallback_parts(
                source,
                max_tokens,
                counter,
                source_start=segment.start,
                source_text=content,
                default_reason="token",
            )
        ]

    body_limit = max(1, max_tokens - counter.count(opening) - counter.count(closing))
    body_parts = _line_fallback_parts(
        content[body_start:body_end],
        body_limit,
        counter,
        source_start=body_start,
        source_text=content,
    )
    wrapped: list[_CodePart] = []
    for index, part in enumerate(body_parts):
        line_separator = "\r\n" if opening.endswith("\r\n") else "\n"
        separator = "" if part.content.endswith(("\n", "\r")) else line_separator
        rendered = f"{opening}{part.content}{separator}{closing}"
        if counter.count(rendered) > max_tokens:
            return [
                replace(candidate, prefix_degraded=True)
                for candidate in _line_fallback_parts(
                    source,
                    max_tokens,
                    counter,
                    source_start=segment.start,
                    source_text=content,
                    default_reason="token",
                )
            ]
        unique_start = segment.start if index == 0 else part.source_char_start
        unique_end = segment.end if index == len(body_parts) - 1 else part.source_char_end
        starts = _line_starts(content)
        line_start, line_end = _line_range(starts, unique_start, unique_end)
        wrapped.append(
            _CodePart(
                rendered,
                part.reason,
                line_start,
                line_end,
                unique_start,
                unique_end,
                lexical_degraded=part.lexical_degraded,
            )
        )
    return wrapped


def _parts_for_code_segment(
    content: str,
    segment: _CodeSegment,
    policy: ChunkPolicy,
    counter: TokenCounter,
) -> list[_CodePart]:
    source = content[segment.start:segment.end]
    starts = _line_starts(content)
    if segment.reason == "fence" and counter.count(source) > policy.max_tokens:
        return _split_fenced_segment(content, segment, policy.max_tokens, counter)
    if counter.count(source) <= policy.max_tokens:
        line_start, line_end = _line_range(starts, segment.start, segment.end)
        return [
            _CodePart(
                source,
                segment.reason,
                line_start,
                line_end,
                segment.start,
                segment.end,
            )
        ]
    return _line_fallback_parts(
        source,
        policy.max_tokens,
        counter,
        source_start=segment.start,
        source_text=content,
        default_reason=("line" if segment.reason != "symbol" else "symbol"),
    )


def _handle_code(
    block: AtomicBlock,
    policy: ChunkPolicy,
    counter: TokenCounter,
    context: TypeHandlerContext,
) -> TypeHandlerResult:
    del context
    metadata = _plain_metadata(block)
    raw_symbols = metadata.get("symbols")
    symbols, invalid_count, malformed_count = _validated_symbol_segments(
        block.content, raw_symbols
    )
    gap_count = 0
    if symbols:
        segments, gap_count = _complete_segments(
            block.content, symbols, structural_reason="symbol"
        )
    else:
        fences = _fence_segments(block.content)
        if fences:
            segments, gap_count = _complete_segments(
                block.content, fences, structural_reason="fence"
            )
        else:
            segments = [_CodeSegment(0, len(block.content), "unsplit")]

    drafts: list[ChunkDraft] = []
    used_fallback = bool(invalid_count or malformed_count or gap_count)
    lexical_degraded = False
    prefix_degraded = False
    for segment in segments:
        parts = _parts_for_code_segment(block.content, segment, policy, counter)
        if segment.signature and counter.count(segment.signature) > policy.max_tokens:
            parts = [replace(part, prefix_degraded=True) for part in parts]
        if len(parts) > 1 or any(part.reason in {"line", "token"} for part in parts):
            used_fallback = True
        for part in parts:
            lexical_degraded = lexical_degraded or part.lexical_degraded
            prefix_degraded = prefix_degraded or part.prefix_degraded
            drafts.append(
                _draft(
                    block,
                    part.content,
                    counter,
                    _code_metadata(metadata, part, signature=segment.signature),
                )
            )

    if not drafts:
        raise ValueError("code handler failed to preserve a non-empty source")
    ranges = sorted(
        {
            (
                int(part.metadata["code"]["sourceCharStart"]),
                int(part.metadata["code"]["sourceCharEnd"]),
            )
            for part in drafts
        }
    )
    if ranges[0][0] != 0 or ranges[-1][1] != len(block.content) or any(
        left[1] != right[0] for left, right in zip(ranges, ranges[1:])
    ):
        raise ValueError("code handler emitted incomplete source coverage")

    warnings = ()
    if used_fallback or lexical_degraded or prefix_degraded:
        warnings = (
            ChunkingWarning(
                code=_CODE_FALLBACK_SPLIT,
                message="code used validated structural coverage and bounded fallback",
                metadata={
                    "atomicBlockIndex": block.index,
                    "partCount": len(drafts),
                    "gapCount": gap_count,
                    "invalidSymbolCount": invalid_count,
                    "malformedSymbolMetadataCount": malformed_count,
                    "lexicalDegraded": lexical_degraded,
                    "prefixDegraded": prefix_degraded,
                },
            ),
        )
    return TypeHandlerResult(drafts=tuple(drafts), warnings=warnings)


def _source_identity(block: AtomicBlock) -> str | None:
    for key in ("sourceIdentity", "documentId", "sourceId", "document_id", "source_id"):
        value = block.source_locator.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _validate_context(block: AtomicBlock, context: TypeHandlerContext) -> None:
    if context.previous is None and context.following is None:
        return
    if _source_identity(block) != context.source_identity:
        raise ValueError("context source identity does not match the current block")
    if context.current_position is None:
        raise ValueError("context current position is required")
    if context.previous is not None:
        if context.previous_position != context.current_position - 1:
            raise ValueError("previous context sequence position is not adjacent")
        if _source_identity(context.previous) != context.source_identity:
            raise ValueError("previous context has a different source identity")
    if context.following is not None:
        if context.following_position != context.current_position + 1:
            raise ValueError("following context sequence position is not adjacent")
        if _source_identity(context.following) != context.source_identity:
            raise ValueError("following context has a different source identity")


def _is_eligible_neighbor(
    block: AtomicBlock,
    neighbor: AtomicBlock | None,
    *,
    require_same_page: bool,
) -> bool:
    if neighbor is None:
        return False
    return (
        neighbor.block_type in {BlockType.TEXT, BlockType.LIST, BlockType.QUOTE}
        and (not require_same_page or neighbor.page_no == block.page_no)
        and neighbor.title_path == block.title_path
        and neighbor.parent_structural_id == block.parent_structural_id
    )


def _neighbor_text(
    block: AtomicBlock,
    neighbor: AtomicBlock | None,
    *,
    require_same_page: bool,
) -> str | None:
    if not _is_eligible_neighbor(
        block, neighbor, require_same_page=require_same_page
    ):
        return None
    return _non_empty_text(neighbor.content if neighbor is not None else None)


def _section_line(block: AtomicBlock) -> str | None:
    if not block.title_path:
        return None
    return "Section: " + " > ".join(block.title_path)


@dataclass(frozen=True)
class _LabeledComponent:
    label: str
    value: str
    source_blocks: tuple[AtomicBlock, ...]
    split_reason: str
    source_text: str | None = None


@dataclass(frozen=True)
class _LabeledPiece:
    content: str
    source_blocks: tuple[AtomicBlock, ...]
    split_reason: str
    source_text: str | None
    label: str
    degraded: bool = False


def _labeled_component_pieces(
    component: _LabeledComponent,
    max_tokens: int,
    counter: TokenCounter,
) -> list[_LabeledPiece]:
    prefix = f"{component.label}: "
    rendered = f"{prefix}{component.value}"
    if counter.count(rendered) <= max_tokens:
        return [
            _LabeledPiece(
                rendered,
                component.source_blocks,
                component.split_reason,
                component.source_text,
                component.label,
                degraded=component.split_reason == "marker_fallback",
            )
        ]
    if counter.count(prefix) >= max_tokens:
        raise ValueError("labeled component prefix exceeds token budget")

    initial_limit = max(1, max_tokens - counter.count(prefix))
    for value_limit in _bounded_candidate_limits(initial_limit):
        value_parts = _candidate_token_parts(component.value, value_limit, counter)
        if value_parts is None:
            continue
        rendered_parts = [f"{prefix}{part}" for part in value_parts]
        if all(counter.count(part) <= max_tokens for part in rendered_parts):
            pieces: list[_LabeledPiece] = []
            source_cursor = 0
            for value_part, rendered_part in zip(
                value_parts, rendered_parts, strict=True
            ):
                source_text = None
                if component.source_text is not None:
                    source_text = component.source_text[
                        source_cursor : source_cursor + len(value_part)
                    ]
                    source_cursor += len(value_part)
                pieces.append(
                    _LabeledPiece(
                        rendered_part,
                        component.source_blocks,
                        "token_fallback",
                        source_text,
                        component.label,
                        degraded=True,
                    )
                )
            if component.source_text is not None and source_cursor != len(
                component.source_text
            ):
                raise ValueError("labeled component source split was not lossless")
            return pieces
    raise ValueError("labeled component could not fit token budget")


def _pack_labeled_components(
    block: AtomicBlock,
    components: Sequence[_LabeledComponent],
    policy: ChunkPolicy,
    counter: TokenCounter,
    metadata_factory: Callable[[Sequence[_LabeledPiece], int, int], Mapping[str, Any]],
    *,
    anchor_blocks: Sequence[AtomicBlock] = (),
) -> tuple[ChunkDraft, ...]:
    pieces = [
        piece
        for component in components
        for piece in _labeled_component_pieces(
            component, policy.max_tokens, counter
        )
    ]
    groups: list[list[_LabeledPiece]] = []
    buffer: list[_LabeledPiece] = []
    for piece in pieces:
        candidate = [*buffer, piece]
        candidate_content = "\n".join(value.content for value in candidate)
        if candidate_content and counter.count(candidate_content) <= policy.max_tokens:
            buffer = candidate
            continue
        if buffer:
            groups.append(buffer)
        buffer = [piece]
    if buffer:
        groups.append(buffer)

    drafts: list[ChunkDraft] = []
    for index, group in enumerate(groups, 1):
        source_blocks = (
            *anchor_blocks,
            *(
                source
                for piece in group
                for source in piece.source_blocks
            ),
        )
        drafts.append(
            _draft(
                block,
                "\n".join(piece.content for piece in group),
                counter,
                metadata_factory(group, index, len(groups)),
                source_blocks=source_blocks,
            )
        )
    return tuple(drafts)


def _handle_image(
    block: AtomicBlock,
    policy: ChunkPolicy,
    counter: TokenCounter,
    context: TypeHandlerContext,
) -> TypeHandlerResult:
    metadata = _plain_metadata(block)
    previous_text = _neighbor_text(
        block, context.previous, require_same_page=True
    )
    following_text = _neighbor_text(
        block, context.following, require_same_page=True
    )
    candidates = (
        ("Caption", _non_empty_text(metadata.get("caption")), block),
        ("OCR", _non_empty_text(metadata.get("ocr")), block),
        ("Alt", _non_empty_text(metadata.get("alt")), block),
        ("Context", previous_text, context.previous),
        ("Context", following_text, context.following),
    )
    components: list[_LabeledComponent] = []
    seen: set[str] = set()
    for label, value, source_block in candidates:
        if value is None or source_block is None:
            continue
        normalized = " ".join(value.split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        components.append(
            _LabeledComponent(
                label,
                normalized,
                (source_block,),
                "component",
            )
        )
    if not components:
        return TypeHandlerResult(
            warnings=(
                ChunkingWarning(
                    code=_IMAGE_WITHOUT_TEXT_SKIPPED,
                    message="image has no caption, OCR, alt text, or eligible neighbor text",
                    metadata={
                        "atomicBlockIndex": block.index,
                        "sourceLocator": _source_locator(block),
                    },
                ),
            )
        )

    section = _section_line(block)
    if section:
        components.insert(
            0,
            _LabeledComponent(
                "Section",
                section.removeprefix("Section: "),
                (block,),
                "component",
            ),
        )

    def image_metadata(
        group: Sequence[_LabeledPiece], index: int, count: int
    ) -> Mapping[str, Any]:
        return {
            "handlerVersion": _HANDLER_VERSION,
            "image": {
                "textSourceCount": len(seen),
                "labels": [piece.label for piece in group],
                "componentDegraded": any(piece.degraded for piece in group),
            },
            "partIndex": index,
            "partCount": count,
        }

    drafts = _pack_labeled_components(
        block,
        components,
        policy,
        counter,
        image_metadata,
        anchor_blocks=(block,),
    )
    warnings = ()
    if any(draft.metadata["image"]["componentDegraded"] for draft in drafts):
        warnings = (
            ChunkingWarning(
                code="IMAGE_COMPONENT_FALLBACK_SPLIT",
                message="an image text component required bounded token fallback",
                metadata={"atomicBlockIndex": block.index, "partCount": len(drafts)},
            ),
        )
    return TypeHandlerResult(drafts=drafts, warnings=warnings)


def _formula_context_components(
    block: AtomicBlock,
    metadata: Mapping[str, Any],
    context: TypeHandlerContext,
) -> list[_LabeledComponent]:
    explanation_candidates = (
        (_non_empty_text(metadata.get("explanation")), block),
        (_neighbor_text(block, context.previous, require_same_page=False), context.previous),
        (_neighbor_text(block, context.following, require_same_page=False), context.following),
    )
    components: list[_LabeledComponent] = []
    seen: set[str] = set()
    for value, source_block in explanation_candidates:
        if value is None or source_block is None:
            continue
        normalized = " ".join(value.split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        components.append(
            _LabeledComponent(
                "Explanation" if not components else "Context",
                normalized,
                (source_block,),
                "explanation",
            )
        )
    return components


def _formula_source_value(block: AtomicBlock, metadata: Mapping[str, Any]) -> str:
    raw_latex = metadata.get("latex")
    if isinstance(raw_latex, str) and raw_latex.strip():
        return raw_latex
    return block.content


def _formula_source_components(
    block: AtomicBlock,
    formula: str,
    policy: ChunkPolicy,
    counter: TokenCounter,
) -> list[_LabeledComponent]:
    if counter.count(f"Formula: {formula}") <= policy.max_tokens:
        return [
            _LabeledComponent(
                "Formula", formula, (block,), "unsplit", source_text=formula
            )
        ]

    environment = re.fullmatch(
        r"(?P<opening>\s*\\begin\{(?P<name>[^}\r\n]+)\})"
        r"(?P<body>.*)"
        r"(?P<closing>\\end\{(?P=name)\}\s*)",
        formula,
        flags=re.DOTALL,
    )
    fragments: list[tuple[str, str]] = []
    if environment is not None:
        opening = environment.group("opening")
        body = environment.group("body")
        closing = environment.group("closing")
        fragments.append((opening, "latex_environment"))
        if body:
            fragments.extend(
                (line, "latex_environment")
                for line in (body.splitlines(keepends=True) or [body])
            )
        fragments.append((closing, "latex_environment"))
    else:
        fragments = [
            (line, "formula_line")
            for line in (formula.splitlines(keepends=True) or [formula])
        ]

    if "".join(fragment for fragment, _ in fragments) != formula:
        raise ValueError("formula structural split did not preserve source")
    return [
        _LabeledComponent(
            "Formula", fragment, (block,), reason, source_text=fragment
        )
        for fragment, reason in fragments
        if fragment
    ]


def _formula_split_reason(group: Sequence[_LabeledPiece]) -> str:
    reasons = {piece.split_reason for piece in group if piece.label == "Formula"}
    if "token_fallback" in reasons or "marker_fallback" in reasons:
        return "token_fallback"
    if "latex_environment" in reasons:
        return "latex_environment"
    if "formula_line" in reasons:
        return "formula_line"
    if "unsplit" in reasons:
        return "unsplit"
    return "context"


def _handle_formula(
    block: AtomicBlock,
    policy: ChunkPolicy,
    counter: TokenCounter,
    context: TypeHandlerContext,
) -> TypeHandlerResult:
    metadata = _plain_metadata(block)
    formula = _formula_source_value(block, metadata)
    if not isinstance(formula, str) or not formula:
        raise ValueError("formula source must not be empty")

    explanation_components = _formula_context_components(block, metadata, context)
    formula_components = _formula_source_components(
        block, formula, policy, counter
    )
    components: list[_LabeledComponent] = []
    section = _section_line(block)
    if section and len(formula_components) == 1 and formula_components[0].split_reason == "unsplit":
        components.append(
            _LabeledComponent(
                "Section",
                section.removeprefix("Section: "),
                (block,),
                "context",
            )
        )
    components.extend(formula_components)
    components.extend(explanation_components)
    explanation_count = len(explanation_components)

    def formula_metadata(
        group: Sequence[_LabeledPiece], index: int, count: int
    ) -> Mapping[str, Any]:
        source_text = "".join(
            piece.source_text or ""
            for piece in group
            if piece.label == "Formula"
        )
        return {
            "handlerVersion": _HANDLER_VERSION,
            "formula": {
                "explanationCount": explanation_count,
                "splitReason": _formula_split_reason(group),
                "partIndex": index,
                "partCount": count,
                "contextDegraded": False,
                "sourceText": source_text or None,
                "componentLabels": [piece.label for piece in group],
                "lexicalDegraded": any(piece.degraded for piece in group),
            },
        }

    drafts = _pack_labeled_components(
        block, components, policy, counter, formula_metadata
    )
    reconstructed = "".join(
        str(draft.metadata["formula"].get("sourceText") or "")
        for draft in drafts
    )
    if reconstructed != formula:
        raise ValueError("formula handler did not preserve source representation")
    degraded = any(
        draft.metadata["formula"]["splitReason"] == "token_fallback"
        or draft.metadata["formula"]["lexicalDegraded"]
        for draft in drafts
    )
    warnings = ()
    if degraded:
        warnings = (
            ChunkingWarning(
                code="FORMULA_FALLBACK_SPLIT",
                message="formula required bounded labeled token fallback",
                metadata={
                    "atomicBlockIndex": block.index,
                    "partCount": len(drafts),
                    "tokenFallback": True,
                },
            ),
        )
    return TypeHandlerResult(drafts=drafts, warnings=warnings)

def _parse_list_items(content: str) -> list[str]:
    items: list[str] = []
    for line in content.splitlines():
        match = re.match(r"\s*(?:[-*+]\s+|\d+[.)]\s+)(.+)", line)
        if match:
            items.append(match.group(1).strip())
    return items


def _handle_list(
    block: AtomicBlock,
    policy: ChunkPolicy,
    counter: TokenCounter,
    context: TypeHandlerContext,
) -> TypeHandlerResult:
    metadata = _plain_metadata(block)
    intro = _non_empty_text(metadata.get("intro"))
    intro_source: AtomicBlock = block
    if intro is None and _is_eligible_neighbor(
        block, context.previous, require_same_page=True
    ):
        intro = _non_empty_text(context.previous.content if context.previous else None)
        if context.previous is not None:
            intro_source = context.previous
    raw_items = metadata.get("items")
    if isinstance(raw_items, (list, tuple)):
        items = [str(item).strip() for item in raw_items if str(item).strip()]
    else:
        items = _parse_list_items(block.content)
    if not items:
        items = [block.content.strip()]

    item_start_value = metadata.get("itemStart", 1)
    item_start = (
        item_start_value
        if isinstance(item_start_value, int) and not isinstance(item_start_value, bool)
        else 1
    )
    prefix_plan = _prepare_repeated_prefix(intro or "", policy.max_tokens, counter)
    drafts: list[ChunkDraft] = []
    if prefix_plan.degraded:
        for index, part in enumerate(prefix_plan.standalone_parts, 1):
            drafts.append(
                _draft(
                    block,
                    part,
                    counter,
                    {
                        "handlerVersion": _HANDLER_VERSION,
                        "list": {
                            "itemStart": item_start,
                            "itemEnd": item_start - 1,
                            "repeatedIntroTokens": 0,
                            "introDegraded": True,
                            "splitReason": "intro_fallback",
                            "partIndex": index,
                            "partCount": len(prefix_plan.standalone_parts),
                        },
                    },
                    source_blocks=(intro_source,),
                )
            )

    rendered_items = [f"- {item}" for item in items]
    packed = _pack_units(
        rendered_items,
        prefix_plan.repeated,
        policy.max_tokens,
        counter,
    )
    fragment_prefix_degraded = any(entry[3] for entry in packed)
    for content, start, end, prefix_degraded in packed:
        includes_intro = bool(prefix_plan.repeated) and not prefix_degraded
        source_blocks = (intro_source, block) if includes_intro else (block,)
        drafts.append(
            _draft(
                block,
                content,
                counter,
                {
                    "handlerVersion": _HANDLER_VERSION,
                    "list": {
                        "itemStart": item_start + start,
                        "itemEnd": item_start + end,
                        "repeatedIntroTokens": (
                            counter.count(prefix_plan.repeated)
                            if prefix_plan.repeated and not prefix_degraded
                            else 0
                        ),
                        "introDegraded": prefix_plan.degraded or prefix_degraded,
                        "splitReason": "item_group",
                    },
                },
                source_blocks=source_blocks,
            )
        )
    warnings = ()
    if prefix_plan.degraded or fragment_prefix_degraded:
        degradation = (
            "intro_fragment_fallback"
            if fragment_prefix_degraded
            else "intro_standalone"
        )
        warnings = (
            ChunkingWarning(
                code="LIST_PREFIX_DEGRADED",
                message="list introduction could not be repeated on every fragment",
                metadata={
                    "atomicBlockIndex": block.index,
                    "degradation": degradation,
                    "partCount": len(drafts),
                },
            ),
        )
    return TypeHandlerResult(drafts=tuple(drafts), warnings=warnings)


TypeHandler = Callable[
    [AtomicBlock, ChunkPolicy, TokenCounter, TypeHandlerContext],
    TypeHandlerResult,
]

_RAW_TYPE_HANDLER_REGISTRY: dict[BlockType, TypeHandler] = {
    BlockType.TABLE: _handle_table,
    BlockType.CODE: _handle_code,
    BlockType.IMAGE: _handle_image,
    BlockType.FORMULA: _handle_formula,
    BlockType.LIST: _handle_list,
}


def handle_typed_block(
    block: AtomicBlock,
    policy: ChunkPolicy,
    token_counter: TokenCounter,
    *,
    context: TypeHandlerContext | None = None,
) -> TypeHandlerResult:
    """Validate and dispatch one atomic block without external state access."""

    if not isinstance(block, AtomicBlock):
        raise ValueError("block must be an AtomicBlock")
    if not isinstance(policy, ChunkPolicy):
        raise ValueError("policy must be a ChunkPolicy")
    counter = require_token_counter(token_counter)
    handler_context = context or TypeHandlerContext()
    _validate_context(block, handler_context)
    try:
        handler = _RAW_TYPE_HANDLER_REGISTRY[block.block_type]
    except KeyError as exc:
        raise ValueError(
            f"no content type handler registered for {block.block_type.value}"
        ) from exc
    result = handler(block, policy, counter, handler_context)
    for draft in result.drafts:
        actual_tokens = counter.count(draft.content)
        if draft.token_count != actual_tokens:
            raise ValueError("type handler emitted an inconsistent token_count")
        if actual_tokens > policy.max_tokens:
            raise ValueError("type handler emitted a chunk over max_tokens")
        if draft.overlap_prefix_tokens != 0 or "overlap" in draft.metadata:
            raise ValueError("non-prose type handlers must not apply generic overlap")
    return result


def _validated_handler(expected_type: BlockType) -> TypeHandler:
    def adapter(
        block: AtomicBlock,
        policy: ChunkPolicy,
        token_counter: TokenCounter,
        context: TypeHandlerContext,
    ) -> TypeHandlerResult:
        if not isinstance(block, AtomicBlock) or block.block_type != expected_type:
            raise ValueError(
                f"handler for {expected_type.value} requires a matching AtomicBlock"
            )
        return handle_typed_block(
            block, policy, token_counter, context=context
        )

    return adapter


TYPE_HANDLER_REGISTRY: Mapping[BlockType, TypeHandler] = MappingProxyType(
    {
        block_type: _validated_handler(block_type)
        for block_type in _RAW_TYPE_HANDLER_REGISTRY
    }
)


def get_type_handler(block_type: BlockType) -> TypeHandler:
    """Return a validation-enforcing adapter for a supported content type."""

    normalized_type = BlockType(block_type)
    try:
        return TYPE_HANDLER_REGISTRY[normalized_type]
    except KeyError as exc:
        raise ValueError(
            f"no content type handler registered for {normalized_type.value}"
        ) from exc


__all__ = [
    "TYPE_HANDLER_REGISTRY",
    "ChunkDraft",
    "TypeHandler",
    "TypeHandlerContext",
    "TypeHandlerResult",
    "get_type_handler",
    "handle_typed_block",
]
