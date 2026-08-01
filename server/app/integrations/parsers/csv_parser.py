import csv
import io
from pathlib import Path

from server.app.services.chunking.contracts import BlockType

from server.app.integrations.parsers.base import (
    ParsedBlock,
    ParsedDocument,
    ParseRequest,
    ParserAdapter,
    ParserError,
)

# Per-block char budget. Kept well under QA_SPLIT_MAX_BATCH_CHARS (6000) so a
# single chunk always fits one QA-split prompt batch; the header row is
# repeated in every block so each chunk is self-contained for QA generation.
_MAX_BLOCK_CHARS = 4000


class CsvParser(ParserAdapter):
    name = "CSV"
    version = "1.0"
    extensions = frozenset({".csv"})
    mime_types = frozenset({"text/csv", "application/csv"})

    def parse(self, request: ParseRequest) -> ParsedDocument:
        source = request.source
        try:
            # utf-8-sig strips the BOM Excel prepends to UTF-8 CSV exports.
            text = source.content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ParserError(
                "PARSER_DECODE_ERROR", "CSV 文件不是合法 UTF-8 文本"
            ) from exc

        rows = self._read_rows(text)
        if not rows:
            return ParsedDocument(
                parser_name=self.name,
                parser_version=self.version,
                markdown="",
                blocks=[],
                page_count=0,
            )

        header, *data_rows = rows
        header_md = self._header_markdown(header)
        title_path = [Path(source.file_name).stem]

        blocks: list[ParsedBlock] = []
        buffer: list[str] = []
        buffer_chars = 0
        # Physical CSV row numbers, 1-based; the header is row 1.
        row_start = 2

        def flush(row_end: int) -> None:
            nonlocal buffer, buffer_chars, row_start
            if not buffer:
                return
            blocks.append(
                ParsedBlock(
                    index=len(blocks),
                    content="\n".join([*header_md, *buffer]),
                    page_no=1,
                    title_path=list(title_path),
                    source_locator={"rowStart": row_start, "rowEnd": row_end},
                    block_type=BlockType.TABLE,
                    structural_id=f"csv:rows:{row_start}-{row_end}",
                    parent_structural_id=f"csv:{Path(source.file_name).stem}",
                    metadata={
                        "header": list(header),
                        "headerRow": 1,
                        "rowStart": row_start,
                        "rowEnd": row_end,
                    },
                )
            )
            buffer = []
            buffer_chars = 0
            row_start = row_end + 1

        header_chars = sum(len(line) for line in header_md)
        for offset, row in enumerate(data_rows):
            line = self._row_markdown(row, len(header))
            if buffer and header_chars + buffer_chars + len(line) > _MAX_BLOCK_CHARS:
                flush(row_end=offset + 1)
            buffer.append(line)
            buffer_chars += len(line)
        flush(row_end=len(data_rows) + 1)

        markdown = "\n".join(
            [*header_md, *(self._row_markdown(row, len(header)) for row in data_rows)]
        )
        return ParsedDocument(
            parser_name=self.name,
            parser_version=self.version,
            markdown=markdown,
            blocks=blocks,
            page_count=1,
        )

    @staticmethod
    def _read_rows(text: str) -> list[list[str]]:
        sample = text[:8192]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(text), dialect)
        return [row for row in reader if any(cell.strip() for cell in row)]

    @classmethod
    def _header_markdown(cls, header: list[str]) -> list[str]:
        cells = [cls._cell(value) for value in header]
        return [
            "| " + " | ".join(cells) + " |",
            "| " + " | ".join("---" for _ in cells) + " |",
        ]

    @classmethod
    def _row_markdown(cls, row: list[str], width: int) -> str:
        cells = [cls._cell(value) for value in row[:width]]
        cells.extend("" for _ in range(width - len(cells)))
        return "| " + " | ".join(cells) + " |"

    @staticmethod
    def _cell(value: str) -> str:
        return " ".join(value.split()).replace("|", "\\|")
