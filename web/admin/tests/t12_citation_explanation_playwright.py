from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Route, expect, sync_playwright


ROOT = Path(__file__).resolve().parents[3]
SCREENSHOT_DIR = ROOT / "docs" / "development" / "v1.1" / "acceptance"
APP_URL = "http://127.0.0.1:5174/#chat"


def json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)


def fulfill_json(route: Route, payload: dict, status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=json_dumps(payload))


def api_path(route: Route) -> str:
    parsed = urlparse(route.request.url)
    marker = "/api/v1"
    return parsed.path[parsed.path.index(marker) :] if marker in parsed.path else parsed.path


def sse_event(name: str, payload: dict) -> str:
    return f"event: {name}\ndata: {json_dumps(payload)}\n\n"


def mock_api(route: Route) -> None:
    path = api_path(route)
    method = route.request.method

    if method == "GET" and path == "/api/v1/chat/sessions":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "session-refund",
                        "title": "退款咨询",
                        "status": "ACTIVE",
                        "createdAt": "2026-07-05T10:00:00+08:00",
                        "updatedAt": "2026-07-05T10:10:00+08:00",
                    }
                ]
            },
        )
        return

    if method == "GET" and path == "/api/v1/chat/sessions/session-refund/messages":
        fulfill_json(route, {"data": []})
        return

    if method == "POST" and path == "/api/v1/chat/sessions/session-refund/message-runs":
        body = (
            sse_event("run_started", {"runId": "run-refund", "requestId": "req_chat"})
            + sse_event("delta", {"runId": "run-refund", "content": "退款需要主管审批。"})
            + sse_event(
                "citation",
                {
                    "runId": "run-refund",
                    "citationId": "citation-refund",
                    "documentId": "doc-refund",
                    "qaPairId": "qa-refund",
                    "title": "Refund SOP",
                    "pageNo": 1,
                    "quote": "退款需要主管审批。",
                    "rank": 1,
                    "score": 1.93,
                },
            )
            + sse_event("done", {"runId": "run-refund", "messageId": "msg-assistant"})
        )
        route.fulfill(status=200, content_type="text/event-stream", body=body)
        return

    if method == "GET" and path == "/api/v1/citations/citation-refund/source":
        fulfill_json(
            route,
            {
                "citationId": "citation-refund",
                "documentId": "doc-refund",
                "documentTitle": "Refund SOP",
                "documentDeleted": False,
                "pageNo": 1,
                "quote": "退款需要主管审批。",
                "sourceText": "退款申请提交后，由主管审批。",
                "sourceLocator": {"lineStart": 1},
            },
        )
        return

    if method == "GET" and path == "/api/v1/query-runs/run-refund/retrieval-explanation":
        fulfill_json(
            route,
            {
                "runId": "run-refund",
                "question": "退款需要谁审批？",
                "filters": {"authorizedCandidates": 1},
                "stages": {
                    "vector": [{"qaPairId": "qa-refund", "question": "退款需要谁审批？", "score": 0.91}],
                    "text": [{"qaPairId": "qa-refund", "question": "退款需要谁审批？", "score": 1}],
                    "rrf": [{"qaPairId": "qa-refund", "question": "退款需要谁审批？", "rrfScore": 0.032}],
                    "rerank": [{"qaPairId": "qa-refund", "question": "退款需要谁审批？", "rerankScore": 1.93}],
                },
            },
        )
        return

    fulfill_json(route, {"error": {"code": "MOCK_NOT_FOUND", "message": path, "details": {}}, "requestId": "req"}, 404)


def prepare_page(page: Page) -> list[str]:
    console_errors: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type in {"error", "warning"}
        else None,
    )
    page.route("**/*/api/v1/**", mock_api)
    page.route("**/api/v1/**", mock_api)
    page.add_init_script("localStorage.setItem('lingxi_access_token', 'playwright-token')")
    return console_errors


def verify_page(page: Page, screenshot_name: str) -> list[str]:
    errors = prepare_page(page)
    page.goto(APP_URL, wait_until="networkidle")
    page.get_by_label("输入问题").fill("退款需要谁审批？")
    page.get_by_role("button", name="发送").click()

    expect(page.get_by_text("Refund SOP")).to_be_visible()
    expect(page.get_by_text("页码 1")).to_be_visible()
    page.get_by_text("Refund SOP").click()
    expect(page.get_by_role("dialog", name="引用原文")).to_be_visible()
    expect(page.get_by_text("退款申请提交后，由主管审批。")).to_be_visible()
    page.get_by_role("button", name="关闭").click()

    page.get_by_role("button", name="查看").click()
    expect(page.get_by_text("向量召回")).to_be_visible()
    expect(page.get_by_text("全文召回")).to_be_visible()
    expect(page.get_by_text("RRF 融合")).to_be_visible()
    expect(page.get_by_text("ReRank")).to_be_visible()

    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1"):
        raise AssertionError("T12 页面存在水平溢出")
    page.screenshot(path=str(SCREENSHOT_DIR / screenshot_name), full_page=True)
    return errors


def main() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        desktop_page = browser.new_page(viewport={"width": 1440, "height": 900})
        desktop_errors = verify_page(desktop_page, "t12-citation-desktop.png")
        desktop_page.close()
        mobile_page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
        mobile_errors = verify_page(mobile_page, "t12-citation-mobile.png")
        mobile_page.close()
        browser.close()
    all_errors = desktop_errors + mobile_errors
    if all_errors:
        raise AssertionError(f"浏览器控制台存在错误或警告: {all_errors}")
    print("T12 Playwright acceptance passed")


if __name__ == "__main__":
    main()
