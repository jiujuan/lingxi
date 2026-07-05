from server.app.integrations.parsers.base import (
    ParsedDocument,
    ParseRequest,
    ParseSource,
    ParserAdapter,
    ParserError,
)


class MinerUParser(ParserAdapter):
    name = "MINERU"
    version = "stub"

    def supports(self, source: ParseSource) -> bool:
        return source.mime_type in {"application/pdf"} or source.file_name.lower().endswith(
            ".pdf"
        )

    def parse(self, request: ParseRequest) -> ParsedDocument:
        raise ParserError("PARSER_UNAVAILABLE", "MinerU 解析器尚未配置", retryable=True)
