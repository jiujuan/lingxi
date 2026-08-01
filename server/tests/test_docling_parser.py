import httpx
import pytest

from server.app.integrations.parsers import _http as http_module
from server.app.integrations.parsers import docling as docling_module
from server.app.integrations.parsers.base import ParseRequest, ParseSource, ParserError
from server.app.services.chunking.contracts import BlockType
from server.app.integrations.parsers.docling import DoclingClient, DoclingParser


def _patch_transport(monkeypatch, handler):
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(http_module.httpx, "Client", factory)
    monkeypatch.setattr(http_module.time, "sleep", lambda *_: None)


def _client(**overrides) -> DoclingClient:
    options = {
        "timeout_ms": 1000,
        "poll_interval_seconds": 0.1,
        "max_wait_seconds": 30,
        "max_retries": 2,
    }
    options.update(overrides)
    return DoclingClient("http://docling.test", **options)


def _pdf_request() -> ParseRequest:
    return ParseRequest(
        source=ParseSource(
            file_name="手册.pdf", mime_type="application/pdf", content=b"%PDF-1.7"
        )
    )


def _doc() -> dict:
    return {
        "texts": [
            {"self_ref": "#/texts/0", "label": "title", "text": "产品手册",
             "prov": [{"page_no": 1}]},
            {"self_ref": "#/texts/1", "label": "section_header", "level": 1,
             "text": "退款政策", "prov": [{"page_no": 1}]},
            {"self_ref": "#/texts/2", "label": "text", "text": "退款需要主管审批。",
             "prov": [{"page_no": 1}]},
            {"self_ref": "#/texts/3", "label": "list_item", "text": "七天无理由",
             "prov": [{"page_no": 2}]},
            {"self_ref": "#/texts/4", "label": "caption", "text": "表1 退款时限",
             "prov": [{"page_no": 2}]},
            {"self_ref": "#/texts/5", "label": "caption", "text": "流程图",
             "prov": [{"page_no": 3}]},
            {"self_ref": "#/texts/6", "label": "page_header", "text": "机密",
             "prov": [{"page_no": 1}]},
            {"self_ref": "#/texts/7", "label": "formula", "text": "E=mc^2",
             "prov": [{"page_no": 3}]},
            {"self_ref": "#/texts/8", "label": "section_header", "level": 2,
             "text": "特殊情形", "prov": [{"page_no": 2}]},
        ],
        "tables": [
            {
                "self_ref": "#/tables/0",
                "label": "table",
                "captions": [{"$ref": "#/texts/4"}],
                "prov": [{"page_no": 2}],
                "data": {
                    "grid": [
                        [{"text": "类型"}, {"text": "时限"}],
                        [{"text": "普通"}, {"text": "3天|快"}],
                    ]
                },
            }
        ],
        "pictures": [
            {"self_ref": "#/pictures/0", "label": "picture",
             "captions": [{"$ref": "#/texts/5"}], "prov": [{"page_no": 3}]},
            {"self_ref": "#/pictures/1", "label": "picture", "captions": [],
             "prov": [{"page_no": 3}]},
        ],
        "groups": [
            {"self_ref": "#/groups/0", "label": "list",
             "children": [{"$ref": "#/texts/3"}]},
        ],
        "body": {
            "children": [
                {"$ref": "#/texts/0"},
                {"$ref": "#/texts/6"},
                {"$ref": "#/texts/1"},
                {"$ref": "#/texts/2"},
                {"$ref": "#/texts/8"},
                {"$ref": "#/groups/0"},
                {"$ref": "#/tables/0"},
                {"$ref": "#/pictures/0"},
                {"$ref": "#/pictures/1"},
                {"$ref": "#/texts/7"},
            ]
        },
    }


def _success_result(document: dict) -> dict:
    return {"status": "success", "document": document}


def test_async_flow_maps_docling_document(monkeypatch):
    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        if request.url.path == "/v1/convert/file/async":
            return httpx.Response(200, json={"task_id": "t1", "task_status": "pending"})
        if request.url.path == "/v1/status/poll/t1":
            poll_count += 1
            assert request.url.params.get("wait") is not None
            state = "started" if poll_count == 1 else "success"
            return httpx.Response(200, json={"task_id": "t1", "task_status": state})
        if request.url.path == "/v1/result/t1":
            return httpx.Response(
                200,
                json=_success_result(
                    {"md_content": "# 产品手册\n\n正文", "json_content": _doc()}
                ),
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    _patch_transport(monkeypatch, handler)
    parsed = DoclingParser(_client()).parse(_pdf_request())

    assert parsed.parser_name == "DOCLING"
    assert poll_count == 2
    contents = [block.content for block in parsed.blocks]
    assert contents == [
        "退款需要主管审批。",
        "七天无理由",
        "表1 退款时限\n| 类型 | 时限 |\n| --- | --- |\n| 普通 | 3天\\|快 |",
        "[图片] 流程图",
        "E=mc^2",
    ]
    assert parsed.blocks[0].title_path == ["产品手册", "退款政策"]
    assert parsed.blocks[1].title_path == ["产品手册", "退款政策", "特殊情形"]
    assert parsed.blocks[0].page_no == 1
    assert parsed.blocks[2].page_no == 2
    assert parsed.blocks[2].source_locator["selfRef"] == "#/tables/0"
    assert parsed.blocks[2].source_locator["pageNo"] == 2
    assert parsed.page_count == 3
    assert [block.block_type for block in parsed.blocks] == [
        BlockType.TEXT,
        BlockType.LIST,
        BlockType.TABLE,
        BlockType.IMAGE,
        BlockType.FORMULA,
    ]
    assert parsed.blocks[1].metadata["sourceLabel"] == "list_item"
    assert parsed.blocks[2].metadata["selfRef"] == "#/tables/0"
    assert any("IMAGE_WITHOUT_TEXT_SKIPPED" in warning for warning in parsed.warnings)
    assert parsed.markdown.startswith("# 产品手册")


def test_docling_reads_single_page_bbox_from_provenance():
    doc = _doc()
    bbox = {"l": 10, "t": 20, "r": 30, "b": 40}
    doc["texts"][2]["prov"] = [{"page_no": 2, "bbox": bbox}]

    blocks, page_count, _ = DoclingParser._blocks_from_document(doc)
    block = next(item for item in blocks if item.source_locator["selfRef"] == "#/texts/2")

    assert page_count == 3
    assert block.source_locator["pageStart"] == 2
    assert block.source_locator["pageEnd"] == 2
    assert block.metadata["bbox"] == bbox
    assert block.metadata["bboxes"] == [bbox]


def test_docling_preserves_complete_cross_page_provenance_and_bboxes():
    doc = _doc()
    provenance = [
        {"page_no": 2, "bbox": {"l": 10, "t": 20, "r": 30, "b": 40}},
        {"page_no": 5, "bbox": {"l": 1, "t": 2, "r": 3, "b": 4}},
    ]
    doc["texts"][2]["prov"] = provenance

    blocks, page_count, _ = DoclingParser._blocks_from_document(doc)
    block = next(item for item in blocks if item.source_locator["selfRef"] == "#/texts/2")

    assert block.page_no == 2
    assert page_count == 5
    assert block.source_locator["pageNo"] == 2
    assert block.source_locator["pageStart"] == 2
    assert block.source_locator["pageEnd"] == 5
    assert block.metadata["provenance"] == provenance
    assert block.metadata["bboxes"] == [item["bbox"] for item in provenance]


def test_docling_ignores_invalid_provenance_entries_without_losing_valid_ones():
    doc = _doc()
    valid = {"page_no": 4, "bbox": {"l": 1, "t": 2, "r": 3, "b": 4}}
    doc["texts"][2]["prov"] = [None, "bad", {"page_no": "bad"}, {"page_no": 0}, valid]

    blocks, page_count, _ = DoclingParser._blocks_from_document(doc)
    block = next(item for item in blocks if item.source_locator["selfRef"] == "#/texts/2")

    assert block.page_no == 4
    assert page_count == 4
    assert block.source_locator["pageStart"] == 4
    assert block.source_locator["pageEnd"] == 4
    assert block.metadata["provenance"] == [{"page_no": "bad"}, {"page_no": 0}, valid]


def test_docling_self_ref_provenance_is_stable_when_noncontent_nodes_are_inserted():
    baseline_doc = _doc()
    baseline_blocks, _, _ = DoclingParser._blocks_from_document(baseline_doc)
    baseline = next(
        item for item in baseline_blocks if item.source_locator["selfRef"] == "#/texts/2"
    )

    inserted_doc = _doc()
    inserted_doc["groups"].append(
        {
            "self_ref": "#/groups/1",
            "label": "group",
            "children": [
                {"$ref": "#/texts/6"},
                {"$ref": "#/texts/4"},
            ],
        }
    )
    inserted_doc["body"]["children"].insert(3, {"$ref": "#/groups/1"})
    inserted_blocks, _, _ = DoclingParser._blocks_from_document(inserted_doc)
    inserted = next(
        item for item in inserted_blocks if item.source_locator["selfRef"] == "#/texts/2"
    )

    assert inserted.structural_id == baseline.structural_id
    assert inserted.source_locator == baseline.source_locator


def test_submit_sends_repeated_to_formats_and_api_key(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/convert/file/async":
            captured["body"] = request.read()
            captured["api_key"] = request.headers.get("x-api-key")
            return httpx.Response(200, json={"task_id": "t1", "task_status": "success"})
        if request.url.path == "/v1/result/t1":
            return httpx.Response(
                200, json=_success_result({"md_content": "# 标题\n\n内容"})
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    _patch_transport(monkeypatch, handler)
    DoclingParser(_client(api_key="secret-key")).parse(_pdf_request())

    body = captured["body"]
    # httpx 将列表值编码为重复的 multipart 字段——两个 to_formats 都必须在
    assert body.count(b'name="to_formats"') == 2
    assert b"md" in body and b"json" in body
    assert b'name="image_export_mode"' in body
    assert b"placeholder" in body
    assert captured["api_key"] == "secret-key"


def test_transient_503_is_retried_then_succeeds(monkeypatch):
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.path == "/v1/convert/file/async":
            attempts += 1
            if attempts == 1:
                return httpx.Response(503)
            return httpx.Response(200, json={"task_id": "t1", "task_status": "success"})
        if request.url.path == "/v1/result/t1":
            return httpx.Response(
                200, json=_success_result({"md_content": "# 标题\n\n内容"})
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    _patch_transport(monkeypatch, handler)
    parsed = DoclingParser(_client()).parse(_pdf_request())

    assert attempts == 2
    assert parsed.blocks


def test_connection_error_maps_to_retryable_unavailable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _patch_transport(monkeypatch, handler)
    with pytest.raises(ParserError) as exc_info:
        DoclingParser(_client()).parse(_pdf_request())

    assert exc_info.value.code == "PARSER_UNAVAILABLE"
    assert exc_info.value.retryable is True


def test_client_4xx_maps_to_nonretryable_request_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "unsupported"})

    _patch_transport(monkeypatch, handler)
    with pytest.raises(ParserError) as exc_info:
        DoclingParser(_client()).parse(_pdf_request())

    assert exc_info.value.code == "PARSER_REQUEST_ERROR"
    assert exc_info.value.retryable is False


def test_poll_deadline_exceeded_maps_to_retryable_timeout(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/convert/file/async":
            return httpx.Response(200, json={"task_id": "t1", "task_status": "pending"})
        return httpx.Response(200, json={"task_status": "started"})

    _patch_transport(monkeypatch, handler)
    clock = iter([0.0, 100.0, 200.0])
    monkeypatch.setattr(
        docling_module.time, "monotonic", lambda: next(clock, 300.0)
    )

    with pytest.raises(ParserError) as exc_info:
        DoclingParser(_client(max_wait_seconds=30)).parse(_pdf_request())

    assert exc_info.value.code == "PARSER_TIMEOUT"
    assert exc_info.value.retryable is True


def test_task_failure_maps_to_parser_failed(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/convert/file/async":
            return httpx.Response(200, json={"task_id": "t1", "task_status": "pending"})
        return httpx.Response(200, json={"task_status": "failure"})

    _patch_transport(monkeypatch, handler)
    with pytest.raises(ParserError) as exc_info:
        DoclingParser(_client()).parse(_pdf_request())

    assert exc_info.value.code == "PARSER_FAILED"
    assert exc_info.value.retryable is False


def test_unknown_task_state_keeps_polling_until_success(monkeypatch):
    states = iter(["warming_up", "started", "success"])
    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        if request.url.path == "/v1/convert/file/async":
            return httpx.Response(200, json={"task_id": "t1", "task_status": "pending"})
        if request.url.path == "/v1/status/poll/t1":
            poll_count += 1
            return httpx.Response(200, json={"task_status": next(states)})
        if request.url.path == "/v1/result/t1":
            return httpx.Response(
                200, json=_success_result({"md_content": "# 标题\n\n内容"})
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    _patch_transport(monkeypatch, handler)
    parsed = DoclingParser(_client()).parse(_pdf_request())

    assert poll_count == 3
    assert parsed.blocks


def test_markdown_fallback_when_json_content_missing(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/convert/file/async":
            return httpx.Response(200, json={"task_id": "t1", "task_status": "success"})
        return httpx.Response(
            200, json=_success_result({"md_content": "# 标题\n\n正文段落。"})
        )

    _patch_transport(monkeypatch, handler)
    parsed = DoclingParser(_client()).parse(_pdf_request())

    assert [block.content for block in parsed.blocks] == ["正文段落。"]
    assert parsed.blocks[0].metadata["parserFallback"] is True
    assert parsed.blocks[0].metadata["fallbackReason"] == "DOCLING_JSON_CONTENT_MISSING"
    assert any("json_content" in warning for warning in parsed.warnings)


def test_markdown_synthesized_when_md_content_missing(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/convert/file/async":
            return httpx.Response(200, json={"task_id": "t1", "task_status": "success"})
        return httpx.Response(200, json=_success_result({"json_content": _doc()}))

    _patch_transport(monkeypatch, handler)
    parsed = DoclingParser(_client()).parse(_pdf_request())

    assert parsed.markdown.startswith("# 产品手册")
    assert any("合成" in warning for warning in parsed.warnings)


def test_markdown_fallback_when_structured_walk_yields_no_blocks(monkeypatch):
    # docling-serve returns a json_content dict, but its structure yields zero
    # blocks (broken/empty structured export). The full md_content must be used
    # instead of losing the document to a downstream "no chunk" error.
    empty_doc = {"body": {"children": []}}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/convert/file/async":
            return httpx.Response(200, json={"task_id": "t1", "task_status": "success"})
        return httpx.Response(
            200,
            json=_success_result(
                {"md_content": "# 标题\n\n正文段落。", "json_content": empty_doc}
            ),
        )

    _patch_transport(monkeypatch, handler)
    parsed = DoclingParser(_client()).parse(_pdf_request())

    assert [block.content for block in parsed.blocks] == ["正文段落。"]
    assert any("结构化内容为空" in warning for warning in parsed.warnings)


def test_result_without_document_or_with_failure_is_invalid(monkeypatch):
    responses = iter(
        [
            _success_result({}),
            {"status": "failure", "errors": ["conversion failed"]},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/convert/file/async":
            return httpx.Response(200, json={"task_id": "t1", "task_status": "success"})
        return httpx.Response(200, json=next(responses))

    _patch_transport(monkeypatch, handler)
    parser = DoclingParser(_client())

    with pytest.raises(ParserError) as first:
        parser.parse(_pdf_request())
    assert first.value.code == "PARSER_RESPONSE_INVALID"

    with pytest.raises(ParserError) as second:
        parser.parse(_pdf_request())
    assert second.value.code == "PARSER_FAILED"


def test_unconfigured_client_disables_parser():
    parser = DoclingParser(DoclingClient(None))

    assert parser.is_available() is False
    assert parser.supports(_pdf_request().source) is False
