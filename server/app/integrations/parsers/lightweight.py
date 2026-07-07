from server.app.integrations.parsers.base import (
    ParsedDocument,
    ParseRequest,
    ParserAdapter,
    ParserError,
)
from server.app.integrations.parsers.markdown_blocks import split_markdown_blocks


class LightweightParser(ParserAdapter):
    name = "LIGHTWEIGHT"
    version = "1.0"
    extensions = frozenset({".md", ".markdown", ".txt"})
    mime_types = frozenset({"text/markdown", "text/plain"})

    def parse(self, request: ParseRequest) -> ParsedDocument:
        source = request.source
        if not self.supports(source):
            raise ParserError("UNSUPPORTED_FILE_TYPE", "轻量解析器不支持该文件类型")

        try:
            markdown = source.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ParserError("PARSER_DECODE_ERROR", "文件不是合法 UTF-8 文本") from exc

        blocks = split_markdown_blocks(markdown)
        return ParsedDocument(
            parser_name=self.name,
            parser_version=self.version,
            markdown=markdown,
            blocks=blocks,
            page_count=1 if markdown else 0,
        )
