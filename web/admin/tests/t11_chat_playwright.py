from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Route, expect, sync_playwright


ROOT = Path(__file__).resolve().parents[3]
SCREENSHOT_DIR = ROOT / "docs" / "development" / "v1.1" / "acceptance"
APP_URL = "http://127.0.0.1:5174/#chat"

SESSION = {
    "id": "session-refund",
    "title": "退款咨询",
    "status": "ACTIVE",
    "createdAt": "2026-07-05T10:00:00+08:00",
    "updatedAt": "2026-07-05T10:10:00+08:00",
}


def fulfill_json(route: Route, payload: dict, status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=json_dumps(payload))


def json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)


def api_path(route: Route) -> str:
    parsed = urlparse(route.request.url)
    marker = "/api/v1"
    if marker in parsed.path:
        return parsed.path[parsed.path.index(marker) :]
    return parsed.path


def sse_event(name: str, payload: dict) -> str:
    return f"event: {name}\ndata: {json_dumps(payload)}\n\n"


def mock_api(route: Route, sent_message_runs: list[dict]) -> None:
    request = route.request
    path = api_path(route)
    method = request.method

    if method == "GET" and path == "/api/v1/knowledge-spaces":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "space-support",
                        "code": "SUPPORT",
                        "name": "客服知识库",
                        "description": "售后客服知识",
                        "status": "ACTIVE",
                        "sortOrder": 10,
                        "createdAt": "2026-07-05T09:00:00+08:00",
                        "updatedAt": "2026-07-05T09:00:00+08:00",
                    }
                ]
            },
        )
        return

    if method == "GET" and path == "/api/v1/departments":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "dept-support",
                        "code": "SUPPORT",
                        "name": "客服部",
                        "parentId": None,
                        "createdAt": "2026-07-05T09:00:00+08:00",
                        "userCount": 3,
                    }
                ]
            },
        )
        return

    if method == "GET" and path == "/api/v1/knowledge-categories":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "cat-refund",
                        "spaceId": "space-support",
                        "departmentId": "dept-support",
                        "parentId": None,
                        "code": "REFUND",
                        "name": "退款专题",
                        "categoryType": "TOPIC",
                        "description": "退款政策与审批",
                        "status": "ACTIVE",
                        "sortOrder": 20,
                        "createdAt": "2026-07-05T09:00:00+08:00",
                        "updatedAt": "2026-07-05T09:00:00+08:00",
                    }
                ]
            },
        )
        return

    if method == "GET" and path == "/api/v1/chat/sessions":
        fulfill_json(route, {"data": [SESSION]})
        return

    if method == "POST" and path == "/api/v1/chat/sessions":
        fulfill_json(route, SESSION)
        return

    if method == "GET" and path == "/api/v1/chat/sessions/session-refund/messages":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "msg-user",
                        "sessionId": "session-refund",
                        "role": "USER",
                        "content": "退款需要谁审批？",
                        "status": "CREATED",
                        "requestId": "req_chat",
                        "createdAt": "2026-07-05T10:01:00+08:00",
                    },
                    {
                        "id": "msg-assistant",
                        "sessionId": "session-refund",
                        "role": "ASSISTANT",
                        "content": "退款需要主管审批。",
                        "status": "COMPLETED",
                        "requestId": "req_chat",
                        "createdAt": "2026-07-05T10:01:01+08:00",
                    },
                ]
            },
        )
        return

    if method == "POST" and path == "/api/v1/chat/sessions/session-refund/message-runs":
        sent_message_runs.append(request.post_data_json)
        body = (
            sse_event("run_started", {"runId": "run-chat", "requestId": "req_chat"})
            + sse_event("delta", {"runId": "run-chat", "content": "退款需要"})
            + sse_event("delta", {"runId": "run-chat", "content": "主管审批。"})
            + sse_event(
                "citation",
                {
                    "runId": "run-chat",
                    "citationId": "citation-1",
                    "documentId": "doc-refund",
                    "qaPairId": "qa-refund",
                    "quote": "退款需要主管审批。",
                    "rank": 1,
                },
            )
            + sse_event(
                "done",
                {"runId": "run-chat", "messageId": "msg-assistant", "requestId": "req_chat"},
            )
        )
        route.fulfill(status=200, content_type="text/event-stream", body=body)
        return

    if method == "POST" and path == "/api/v1/chat/messages/msg-assistant/feedback":
        fulfill_json(route, {"id": "msg-assistant", "status": "FEEDBACK_UP"})
        return

    fulfill_json(
        route,
        {
            "error": {
                "code": "MOCK_NOT_FOUND",
                "message": f"未配置 mock: {method} {path}",
                "details": {},
            },
            "requestId": "req_mock_not_found",
        },
        status=404,
    )


def prepare_page(page: Page, sent_message_runs: list[dict]) -> list[str]:
    console_errors: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type in {"error", "warning"}
        else None,
    )
    page.route("**/*/api/v1/**", lambda route: mock_api(route, sent_message_runs))
    page.route("**/api/v1/**", lambda route: mock_api(route, sent_message_runs))
    user = {
        "id": "user-playwright",
        "email": "playwright@example.com",
        "name": "Playwright",
        "roles": ["admin"],
        "permissions": [
            "CHAT_READ",
            "DOCUMENT_READ",
            "DASHBOARD_READ",
            "LOG_READ",
            "API_KEY_READ",
            "MODEL_CONFIG_READ",
            "USER_READ",
            "SETTING_READ",
        ],
    }
    page.add_init_script(
        "localStorage.setItem('lingxi_access_token', 'playwright-token');"
        "localStorage.setItem('lingxi_user', "
        + json_dumps(json_dumps(user))
        + ");"
    )
    return console_errors


def verify_chat_page(page: Page, screenshot_name: str) -> list[str]:
    sent_message_runs: list[dict] = []
    errors = prepare_page(page, sent_message_runs)
    page.goto(APP_URL, wait_until="networkidle")

    expect(page.get_by_role("heading", name="知识库问答")).to_be_visible()
    expect(page.get_by_text("退款咨询")).to_be_visible()
    expect(page.get_by_text("退款需要主管审批。").first).to_be_visible()

    expect(page.get_by_text("检索范围")).to_be_visible()
    page.locator("#chat-retrieval-scope-space").select_option("space-support")
    page.locator("#chat-retrieval-scope-department").select_option("dept-support")
    expect(page.locator("#chat-retrieval-scope-category")).to_contain_text("退款专题")
    page.locator("#chat-retrieval-scope-category").select_option("cat-refund")

    composer = page.get_by_label("输入问题")
    composer.fill("退款需要谁审批？")
    page.get_by_role("button", name="发送").click()
    expect(page.get_by_text("退款需要主管审批。").first).to_be_visible()
    expect(page.get_by_text("qa-refund")).to_be_visible()
    assert sent_message_runs[-1] == {
        "content": "退款需要谁审批？",
        "retrievalScope": {
            "spaceId": "space-support",
            "classificationDepartmentId": "dept-support",
            "categoryId": "cat-refund",
        },
    }

    page.get_by_role("button", name="赞").first.click()
    expect(page.get_by_text("FEEDBACK")).not_to_be_visible()
    expect(page.get_by_text("qa-refund")).to_be_visible()

    overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
    if overflow:
        raise AssertionError("Chat 页面存在水平溢出")

    page.screenshot(path=str(SCREENSHOT_DIR / screenshot_name), full_page=True)
    return errors


def main() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        desktop_page = browser.new_page(viewport={"width": 1440, "height": 900})
        desktop_errors = verify_chat_page(desktop_page, "t11-chat-desktop.png")
        desktop_page.close()

        mobile_page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
        mobile_errors = verify_chat_page(mobile_page, "t11-chat-mobile.png")
        mobile_page.close()
        browser.close()

    all_errors = desktop_errors + mobile_errors
    if all_errors:
        raise AssertionError(f"浏览器控制台存在错误或警告: {all_errors}")

    print("T11 Playwright acceptance passed")
    print(f"desktop={SCREENSHOT_DIR / 't11-chat-desktop.png'}")
    print(f"mobile={SCREENSHOT_DIR / 't11-chat-mobile.png'}")


if __name__ == "__main__":
    main()
