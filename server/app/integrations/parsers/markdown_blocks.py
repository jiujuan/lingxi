"""Shared markdown -> typed structural blocks splitter."""

from __future__ import annotations

import re

from server.app.integrations.parsers.base import ParsedBlock
from server.app.services.chunking.contracts import BlockType

_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})([^`]*)$")
_LIST_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
_TABLE_CELL_RE = re.compile(r"^\s*:?-{3,}:?\s*$")
_THEMATIC_BREAK_RE = re.compile(r"^\s*(?:\*\s*){3,}$|^\s*(?:-\s*){3,}$|^\s*(?:_\s*){3,}$")


def _table_cells(line: str) -> list[str] | None:
    """Return GFM table cells only for a genuine multi-column table line."""
    if "|" not in line:
        return None
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    cells = [cell.strip() for cell in stripped.split("|")]
    return cells if len(cells) >= 2 else None


def _is_markdown_table(lines: list[str]) -> bool:
    if len(lines) < 2:
        return False
    header = _table_cells(lines[0])
    separator = _table_cells(lines[1])
    return bool(
        header
        and separator
        and len(header) == len(separator)
        and all(_TABLE_CELL_RE.match(cell) for cell in separator)
    )


def _is_list_lazy_paragraph(line: str) -> bool:
    """Whether an unindented line can legally continue a list paragraph."""
    stripped = line.lstrip()
    return bool(stripped) and not (
        _FENCE_RE.match(stripped)
        or stripped.startswith(">")
        or stripped.startswith("#")
        or _THEMATIC_BREAK_RE.match(stripped)
    )


def _is_list(lines: list[str]) -> bool:
    if not lines or not _LIST_RE.match(lines[0]):
        return False
    # CommonMark permits indented continuations/nested items and lazy paragraph
    # continuation, but another top-level block construct must terminate the
    # list rather than being swallowed by its type classification.
    for line in lines[1:]:
        if _LIST_RE.match(line) or line[:1].isspace():
            continue
        if not _is_list_lazy_paragraph(line):
            return False
    return True


def _is_quote(lines: list[str]) -> bool:
    if not lines or not lines[0].lstrip().startswith(">"):
        return False
    # Blockquotes allow lazy continuation lines after a quoted paragraph.
    return all(bool(line.strip()) for line in lines[1:])


def _block_kind(content: str) -> tuple[BlockType, dict]:
    """Classify a whole Markdown block without applying token boundaries."""
    lines = content.splitlines()
    first = lines[0].strip() if lines else ""
    fence = _FENCE_RE.match(first)
    if fence:
        info = fence.group(2).strip()
        language = info.split(maxsplit=1)[0] if info else ""
        metadata = {"sourceLabel": "markdown_fence"}
        if language:
            metadata = {"language": language, **metadata}
        return BlockType.CODE, metadata
    if _is_markdown_table(lines):
        return BlockType.TABLE, {"sourceLabel": "markdown_table"}
    if _is_list(lines):
        return BlockType.LIST, {"sourceLabel": "markdown_list"}
    if _is_quote(lines):
        return BlockType.QUOTE, {"sourceLabel": "markdown_quote"}
    return BlockType.TEXT, {"sourceLabel": "markdown_text"}


def split_markdown_blocks(markdown: str) -> list[ParsedBlock]:
    """Split Markdown only at document structure and preserve line locators.

    Headings update a stable section parent id. Fenced code remains atomic even
    when it contains blank lines; ChunkingService owns any later size split.
    """
    blocks: list[ParsedBlock] = []
    title_path: list[str] = []
    buffer: list[str] = []
    block_start_line = 1
    fence_marker: str | None = None

    def section_id() -> str | None:
        return "markdown:section:" + "/".join(title_path) if title_path else None

    def flush(end_line: int) -> None:
        nonlocal buffer, block_start_line
        content = "\n".join(buffer).strip()
        if content:
            block_type, metadata = _block_kind(content)
            blocks.append(
                ParsedBlock(
                    index=len(blocks),
                    content=content,
                    page_no=1,
                    title_path=list(title_path),
                    source_locator={"lineStart": block_start_line, "lineEnd": end_line},
                    block_type=block_type,
                    structural_id=f"markdown:line:{block_start_line}",
                    parent_structural_id=section_id(),
                    metadata=metadata,
                )
            )
        buffer = []
        block_start_line = end_line + 1

    lines = markdown.splitlines()
    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if fence_marker is not None:
            buffer.append(line)
            if stripped.startswith(fence_marker):
                fence_marker = None
                flush(line_no)
            continue

        if stripped.startswith("#"):
            flush(line_no - 1)
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped[level:].strip()
            if title:
                title_path = title_path[: max(level - 1, 0)] + [title]
            block_start_line = line_no + 1
            continue
        if not stripped:
            flush(line_no - 1)
            block_start_line = line_no + 1
            continue
        fence = _FENCE_RE.match(stripped)
        is_top_level = not line[:1].isspace()
        # A top-level fence or quote begins a new structural block even when a
        # preceding list has no blank separator. An indented fence remains part
        # of its list item and is intentionally emitted as LIST content.
        if buffer and is_top_level and (fence or stripped.startswith(">")):
            flush(line_no - 1)
        if not buffer:
            block_start_line = line_no
        buffer.append(line)
        if fence:
            fence_marker = fence.group(1)[0] * len(fence.group(1))

    flush(len(lines))
    return blocks


def markdown_from_blocks(blocks: list[ParsedBlock]) -> str:
    """Synthesize markdown from structured parser output."""
    lines: list[str] = []
    emitted_path: list[str] = []
    for block in blocks:
        if block.title_path != emitted_path:
            for depth, title in enumerate(block.title_path, start=1):
                if depth > len(emitted_path) or emitted_path[depth - 1] != title:
                    lines.append("#" * depth + " " + title)
            emitted_path = list(block.title_path)
        lines.append(block.content)
        lines.append("")
    return "\n".join(lines).strip()
