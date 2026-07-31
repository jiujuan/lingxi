from server.app.integrations.parsers.base import ParseRequest, ParseSource, ParserError
from server.app.services.chunking.contracts import BlockType
from server.app.integrations.parsers.csv_parser import _MAX_BLOCK_CHARS, CsvParser


def _parse(content: bytes, file_name: str = "员工名单.csv"):
    return CsvParser().parse(
        ParseRequest(
            source=ParseSource(
                file_name=file_name, mime_type="text/csv", content=content
            )
        )
    )


def test_csv_parser_builds_markdown_table_blocks():
    parsed = _parse("姓名,部门,备注\n张三,售后,负责退款|发票\n李四,财务,\n".encode())

    assert parsed.parser_name == "CSV"
    assert parsed.page_count == 1
    assert len(parsed.blocks) == 1
    block = parsed.blocks[0]
    lines = block.content.splitlines()
    assert lines[0] == "| 姓名 | 部门 | 备注 |"
    assert lines[1] == "| --- | --- | --- |"
    assert lines[2] == "| 张三 | 售后 | 负责退款\\|发票 |"
    assert lines[3] == "| 李四 | 财务 |  |"
    assert block.title_path == ["员工名单"]
    assert block.page_no == 1
    assert block.source_locator == {"rowStart": 2, "rowEnd": 3}
    assert block.block_type is BlockType.TABLE
    assert block.metadata == {
        "header": ["姓名", "部门", "备注"],
        "rowStart": 2,
        "rowEnd": 3,
        "headerRow": 1,
    }
    assert parsed.markdown.startswith("| 姓名 |")


def test_csv_parser_sniffs_semicolon_delimiter_and_strips_bom():
    content = "﻿姓名;部门\n张三;售后\n".encode()

    parsed = _parse(content)

    assert parsed.blocks[0].content.splitlines()[0] == "| 姓名 | 部门 |"
    assert "张三" in parsed.blocks[0].content


def test_csv_parser_chunks_long_files_with_self_contained_headers():
    rows = "\n".join(f"row{i},{'值' * 80}" for i in range(200))
    parsed = _parse(f"编号,内容\n{rows}\n".encode())

    assert len(parsed.blocks) > 1
    row_cursor = 2
    for block in parsed.blocks:
        lines = block.content.splitlines()
        # 每个块都以表头开头，保证 QA 拆分时上下文自包含
        assert lines[0] == "| 编号 | 内容 |"
        assert lines[1] == "| --- | --- |"
        assert len(block.content) <= _MAX_BLOCK_CHARS + 200
        assert block.source_locator["rowStart"] == row_cursor
        row_cursor = block.source_locator["rowEnd"] + 1
    assert parsed.blocks[-1].source_locator["rowEnd"] == 201


def test_csv_parser_rejects_non_utf8():
    try:
        _parse("姓名,部门\n张三,售后\n".encode("gbk"))
    except ParserError as exc:
        assert exc.code == "PARSER_DECODE_ERROR"
        assert exc.retryable is False
    else:  # pragma: no cover
        raise AssertionError("expected ParserError")


def test_csv_parser_handles_empty_and_header_only_files():
    assert _parse(b"").blocks == []
    assert _parse(b"").page_count == 0

    # 只有表头没有数据行：没有可检索内容，不产出块
    header_only = _parse("姓名,部门\n".encode())
    assert header_only.blocks == []
    assert header_only.page_count == 1
