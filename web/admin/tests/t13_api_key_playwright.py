from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Route, expect, sync_playwright


ROOT = Path(__file__).resolve().parents[3]
SCREENSHOT_DIR = ROOT / "docs" / "development" / "v1.1" / "acceptance"
APP_URL = "http://127.0.0.1:5174/#api-keys"


def json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)


def fulfill_json(route: Route, payload: dict, status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=json_dumps(payload))


def api_path(route: Route) -> str:
    parsed = urlparse(route.request.url)
    marker = "/api/v1"
    return parsed.path[parsed.path.index(marker) :] if marker in parsed.path else parsed.path


KEY = {
    "id": "key-1",
    "name": "Internal Copilot",
    "keyPrefix": "lk_live_abcd123",
    "status": "ACTIVE",
    "scopes": ["chat:read", "knowledge:query"],
    "allowedDepartmentIds": [],
    "allowedRoleIds": [],
    "rateLimitPerMinute": 60,
    "lastUsedAt": None,
    "expiresAt": None,
    "createdAt": "2026-07-05T10:00:00+08:00",
}


def mock_api(route: Route) -> None:
    path = api_path(route)
    method = route.request.method
    if method == "GET" and path == "/api/v1/api-keys":
        fulfill_json(route, {"data": [KEY]})
        return
    if method == "GET" and path == "/api/v1/api-call-logs":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "log-1",
                        "keyPrefix": "lk_live_abcd123",
                        "path": "/v1/chat/completions",
                        "method": "POST",
                        "statusCode": 200,
                        "latencyMs": 32,
                        "errorCode": None,
                        "requestId": "req_api",
                        "createdAt": "2026-07-05T10:01:00+08:00",
                    }
                ]
            },
        )
        return
    if method == "POST" and path == "/api/v1/api-keys":
        fulfill_json(route, {**KEY, "id": "key-new", "key": "lk_live_created_secret", "warning": "密钥明文只展示一次，请妥善保存。"})
        return
    if method == "POST" and path == "/api/v1/api-keys/key-1/disable":
        fulfill_json(route, {**KEY, "status": "DISABLED"})
        return
    if method == "POST" and path == "/api/v1/api-keys/key-1/rotations":
        fulfill_json(route, {**KEY, "key": "lk_live_rotated_secret", "warning": "密钥明文只展示一次，请妥善保存。"})
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
    expect(page.get_by_role("heading", name="内部系统访问密钥")).to_be_visible()
    expect(page.get_by_text("lk_live_abcd123", exact=True)).to_be_visible()
    expect(page.get_by_text("req_api")).to_be_visible()

    page.get_by_role("button", name="创建 Key").click()
    page.get_by_role("button", name="创建", exact=True).click()
    expect(page.get_by_text("lk_live_created_secret")).to_be_visible()
    page.get_by_role("button", name="关闭").click()
    expect(page.get_by_text("lk_live_created_secret")).not_to_be_visible()

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="轮换").first.click()
    expect(page.get_by_text("lk_live_rotated_secret")).to_be_visible()
    page.get_by_role("button", name="关闭").click()

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="禁用").first.click()

    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1"):
        raise AssertionError("T13 页面存在水平溢出")
    page.screenshot(path=str(SCREENSHOT_DIR / screenshot_name), full_page=True)
    return errors


def main() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        desktop_page = browser.new_page(viewport={"width": 1440, "height": 900})
        desktop_errors = verify_page(desktop_page, "t13-api-key-desktop.png")
        desktop_page.close()
        mobile_page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
        mobile_errors = verify_page(mobile_page, "t13-api-key-mobile.png")
        mobile_page.close()
        browser.close()
    all_errors = desktop_errors + mobile_errors
    if all_errors:
        raise AssertionError(f"浏览器控制台存在错误或警告: {all_errors}")
    print("T13 Playwright acceptance passed")


if __name__ == "__main__":
    main()
