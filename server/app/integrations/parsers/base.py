from dataclasses import dataclass, field
from pathlib import Path

from server.app.services.chunking.contracts import BlockType


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
    block_type: BlockType = BlockType.TEXT
    structural_id: str | None = None
    parent_structural_id: str | None = None
    metadata: dict = field(default_factory=dict)


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
    #: lowercase, dot-prefixed suffixes this parser accepts (e.g. ".pdf")
    extensions: frozenset[str] = frozenset()
    #: exact mime types this parser accepts
    mime_types: frozenset[str] = frozenset()

    def is_available(self) -> bool:
        """Whether the parser can actually run (e.g. its backing service is
        configured). Unavailable parsers are never selected and their formats
        are not advertised to the upload gate."""
        return True

    def supports(self, source: ParseSource) -> bool:
        if not self.is_available():
            return False
        # Suffix first: the client-supplied mime type is untrusted and often
        # defaults to application/octet-stream.
        suffix = Path(source.file_name).suffix.lower()
        return suffix in self.extensions or source.mime_type in self.mime_types

    def parse(self, request: ParseRequest) -> ParsedDocument:
        raise NotImplementedError
