from dataclasses import dataclass, field


class ParserError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class ParseSource:
    file_name: str
    mime_type: str
    content: bytes
    object_key: str | None = None


@dataclass(frozen=True)
class ParseRequest:
    source: ParseSource
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedBlock:
    index: int
    content: str
    page_no: int | None = None
    title_path: list[str] = field(default_factory=list)
    source_locator: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedDocument:
    parser_name: str
    parser_version: str
    markdown: str
    blocks: list[ParsedBlock]
    page_count: int | None = None
    warnings: list[str] = field(default_factory=list)


class ParserAdapter:
    name: str
    version: str

    def supports(self, source: ParseSource) -> bool:
        raise NotImplementedError

    def parse(self, request: ParseRequest) -> ParsedDocument:
        raise NotImplementedError
