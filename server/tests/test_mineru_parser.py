import json

import httpx
import pytest

from server.app.integrations.parsers import mineru as mineru_module
from server.app.integrations.parsers.base import ParseRequest, ParseSource, ParserError
from server.app.integrations.parsers.mineru import MinerUClient, MinerUParser


def _patch_transport(monkeypatch, handler):
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(mineru_module.httpx, "Client", factory)
    monkeypatch.setattr(mineru_module.time, "sleep", lambda *_: None)


def _client(**overrides) -> MinerUClient:
    options = {
        "timeout_ms": 1000,
        "poll_interval_seconds": 0.1,
        "max_wait_seconds": 30,
        "max_retries": 2,
    }
    options.update(overrides)
    return MinerUClient("http://mineru.test", **options)


def _pdf_request() -> ParseRequest:
    return ParseRequest(
        source=ParseSource(
            file_name="报告.pdf", mime_type="application/pdf", content=b"%PDF-1.7"
        )
    )


_CONTENT_LIST = [
    {"type": "text", "text": "第一章 退款流程", "text_level": 1, "page_idx": 0},
    {"type": "text", "text": "退款需要主管审批。", "page_idx": 0},
    {
        "type": "table",
        "table_caption": ["表1 退款时限"],
        "table_body": "<table><tr><td>3天</td></tr></table>",
        "page_idx": 1,
    },
    {"type": "image", "image_caption": [], "page_idx": 1},
    {"type": "image", "image_caption": ["流程图"], "page_idx": 2},
    {"type": "equation", "text": "E=mc^2", "page_idx": 2},
]


def test_direct_result_mode_maps_content_list(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/file_parse"
        return httpx.Response(
            200,
            json={
                "results": {
                    "报告.pdf": {
                        "md_content": "# 第一章 退款流程\n\n退款需要主管审批。",
                        "content_list": _CONTENT_LIST,
                    }
                }
            },
        )

    _patch_transport(monkeypatch, handler)
    parsed = MinerUParser(_client()).parse(_pdf_request())

    assert parsed.parser_name == "MINERU"
    assert parsed.page_count == 3
    contents = [block.content for block in parsed.blocks]
    assert contents == [
        "退款需要主管审批。",
        "表1 退款时限\n<table><tr><td>3天</td></tr></table>",
        "[图片] 流程图",
        "E=mc^2",
    ]
    first = parsed.blocks[0]
    assert first.page_no == 1
    assert first.title_path == ["第一章 退款流程"]
    assert first.source_locator == {"pageNo": 1, "blockIndex": 1}
    assert parsed.blocks[1].page_no == 2
    assert any("跳过 1 张" in warning for warning in parsed.warnings)
    assert parsed.markdown.startswith("# 第一章 退款流程")


def test_task_poll_mode_submits_then_fetches_result(monkeypatch):
    poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        if request.url.path == "/file_parse":
            return httpx.Response(200, json={"task_id": "task-1"})
        if request.url.path == "/tasks/task-1":
            poll_count += 1
            state = "pending" if poll_count == 1 else "done"
            return httpx.Response(200, json={"state": state})
        if request.url.path == "/tasks/task-1/result":
            return httpx.Response(
                200,
                json={"data": {"md_content": "# 标题\n\n正文段落。"}},
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    _patch_transport(monkeypatch, handler)
    parsed = MinerUParser(_client()).parse(_pdf_request())

    assert poll_count == 2
    assert [block.content for block in parsed.blocks] == ["正文段落。"]
    assert any("content_list" in warning for warning in parsed.warnings)


def test_transient_503_is_retried_then_succeeds(monkeypatch):
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"md_content": "# 标题\n\n内容。"})

    _patch_transport(monkeypatch, handler)
    parsed = MinerUParser(_client()).parse(_pdf_request())

    assert attempts == 2
    assert parsed.blocks


def test_connection_error_maps_to_retryable_unavailable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _patch_transport(monkeypatch, handler)
    with pytest.raises(ParserError) as exc_info:
        MinerUParser(_client()).parse(_pdf_request())

    assert exc_info.value.code == "PARSER_UNAVAILABLE"
    assert exc_info.value.retryable is True


def test_client_4xx_maps_to_nonretryable_request_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "unsupported"})

    _patch_transport(monkeypatch, handler)
    with pytest.raises(ParserError) as exc_info:
        MinerUParser(_client()).parse(_pdf_request())

    assert exc_info.value.code == "PARSER_REQUEST_ERROR"
    assert exc_info.value.retryable is False


def test_poll_deadline_exceeded_maps_to_retryable_timeout(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/file_parse":
            return httpx.Response(200, json={"task_id": "task-slow"})
        return httpx.Response(200, json={"state": "running"})

    _patch_transport(monkeypatch, handler)
    clock = iter([0.0, 100.0, 200.0])
    monkeypatch.setattr(
        mineru_module.time, "monotonic", lambda: next(clock, 300.0)
    )

    with pytest.raises(ParserError) as exc_info:
        MinerUParser(_client(max_wait_seconds=30)).parse(_pdf_request())

    assert exc_info.value.code == "PARSER_TIMEOUT"
    assert exc_info.value.retryable is True


def test_server_side_task_failure_is_not_retryable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/file_parse":
            return httpx.Response(200, json={"task_id": "task-bad"})
        return httpx.Response(200, json={"state": "failed", "error": "文件损坏"})

    _patch_transport(monkeypatch, handler)
    with pytest.raises(ParserError) as exc_info:
        MinerUParser(_client()).parse(_pdf_request())

    assert exc_info.value.code == "PARSER_FAILED"
    assert exc_info.value.retryable is False
    assert "文件损坏" in exc_info.value.message


def test_content_list_as_json_string_and_missing_markdown(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"content_list": json.dumps(_CONTENT_LIST)}
        )

    _patch_transport(monkeypatch, handler)
    parsed = MinerUParser(_client()).parse(_pdf_request())

    assert len(parsed.blocks) == 4
    # markdown 由结构化内容合成，标题按 title_path 还原
    assert parsed.markdown.startswith("# 第一章 退款流程")
    assert any("合成" in warning for warning in parsed.warnings)


def test_payload_without_result_is_invalid(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    _patch_transport(monkeypatch, handler)
    with pytest.raises(ParserError) as exc_info:
        MinerUParser(_client()).parse(_pdf_request())

    assert exc_info.value.code == "PARSER_RESPONSE_INVALID"


def test_unconfigured_client_disables_parser():
    parser = MinerUParser(MinerUClient(None))

    assert parser.is_available() is False
    assert parser.supports(_pdf_request().source) is False
