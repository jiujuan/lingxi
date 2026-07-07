"""Shared markdown -> blocks splitter used by every parser that ends up with
markdown output (LightweightParser natively, MinerUParser as fallback).

Splitting rules: ATX headings open a new ``title_path`` breadcrumb level and
are not emitted as blocks; blank lines close the current block. Locators are
line-based ``{lineStart, lineEnd}`` and ``page_no`` is always 1 — parsers with
real pagination (MinerU content_list) build their own blocks instead.
"""

from server.app.integrations.parsers.base import ParsedBlock


def split_markdown_blocks(markdown: str) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    title_path: list[str] = []
    buffer: list[str] = []
    block_start_line = 1

    def flush(end_line: int) -> None:
        nonlocal buffer, block_start_line
        content = "\n".join(buffer).strip()
        if content:
            blocks.append(
                ParsedBlock(
                    index=len(blocks),
                    content=content,
                    page_no=1,
                    title_path=list(title_path),
                    source_locator={
                        "lineStart": block_start_line,
                        "lineEnd": end_line,
                    },
                )
            )
        buffer = []
        block_start_line = end_line + 1

    for line_no, line in enumerate(markdown.splitlines(), start=1):
        stripped = line.strip()
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
        if not buffer:
            block_start_line = line_no
        buffer.append(line)

    flush(len(markdown.splitlines()))
    return blocks


def markdown_from_blocks(blocks: list[ParsedBlock]) -> str:
    """Synthesize a markdown artifact from structured blocks — used by heavy
    parsers when the service returned structured content but no markdown."""
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
