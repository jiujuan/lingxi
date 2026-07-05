from pathlib import Path

from server.app.integrations.parsers.base import (
    ParsedBlock,
    ParsedDocument,
    ParseRequest,
    ParseSource,
    ParserAdapter,
    ParserError,
)


class LightweightParser(ParserAdapter):
    name = "LIGHTWEIGHT"
    version = "1.0"

    def supports(self, source: ParseSource) -> bool:
        suffix = Path(source.file_name).suffix.lower()
        return suffix in {".md", ".markdown", ".txt"} or source.mime_type in {
            "text/markdown",
            "text/plain",
        }

    def parse(self, request: ParseRequest) -> ParsedDocument:
        source = request.source
        if not self.supports(source):
            raise ParserError("UNSUPPORTED_FILE_TYPE", "轻量解析器不支持该文件类型")

        try:
            markdown = source.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ParserError("PARSER_DECODE_ERROR", "文件不是合法 UTF-8 文本") from exc

        blocks = self._split_blocks(markdown)
        return ParsedDocument(
            parser_name=self.name,
            parser_version=self.version,
            markdown=markdown,
            blocks=blocks,
            page_count=1 if markdown else 0,
        )

    def _split_blocks(self, markdown: str) -> list[ParsedBlock]:
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
