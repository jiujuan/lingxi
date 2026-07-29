from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Route, expect, sync_playwright


ROOT = Path(__file__).resolve().parents[3]
SCREENSHOT_DIR = ROOT / "docs" / "development" / "v1.1" / "acceptance"
APP_URL = "http://127.0.0.1:5174"


def json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)


def fulfill_json(route: Route, payload: dict, status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=json_dumps(payload))


def api_path(route: Route) -> str:
    parsed = urlparse(route.request.url)
    marker = "/api/v1"
    return parsed.path[parsed.path.index(marker) :] if marker in parsed.path else parsed.path


SETTINGS = {
    "filePolicy": {
        "maxFileSizeMb": 10,
        "allowedExtensions": [".md", ".txt"],
        "defaultParser": "lightweight",
        "ocrEnabled": False,
        "fallbackEnabled": True,
    },
    "retrievalPolicy": {
        "vectorTopK": 20,
        "textTopK": 20,
        "finalTopK": 5,
        "lowConfidenceThreshold": 1.35,
    },
    "rateLimitPolicy": {"apiKeyDefaultPerMinute": 60, "chatPerMinute": 60},
    "storagePolicy": {"backend": "local", "bucket": None, "prefix": ".data/object-storage"},
    "retentionPolicy": {
        "apiCallLogDays": 90,
        "auditLogDays": 365,
        "taskRunDays": 180,
        "softDeleteDays": 30,
    },
    "effectiveScopes": {
        "filePolicy": "NEW_TASKS",
        "retrievalPolicy": "NEW_SESSIONS",
        "rateLimitPolicy": "IMMEDIATE",
        "storagePolicy": "NEW_TASKS",
        "retentionPolicy": "MAINTENANCE_WINDOW",
    },
}

AUTH_USER = {
    "id": "playwright-admin",
    "email": "admin@lingxi.ai",
    "name": "管理员",
    "roles": ["系统管理员"],
    "permissions": [
        "DASHBOARD_READ",
        "LOG_READ",
        "TASK_RETRY",
        "SETTING_READ",
    ],
}


def mock_api(route: Route) -> None:
    path = api_path(route)
    method = route.request.method

    if method == "GET" and path == "/api/v1/dashboard/summary":
        fulfill_json(
            route,
            {
                "metrics": {
                    "documentCount": 8,
                    "qaPairCount": 42,
                    "taskSuccessRate": 92.5,
                    "taskFailureRate": 7.5,
                    "apiCallCount": 128,
                },
                "ingestionHealth": {
                    "successRate": 92.5,
                    "failureRate": 7.5,
                    "stages": [
                        {"stage": "PARSING", "successCount": 12, "failureCount": 1, "totalCount": 13},
                        {"stage": "EMBEDDING", "successCount": 11, "failureCount": 0, "totalCount": 11},
                    ],
                    "trend": [],
                },
                "qaHealth": {
                    "queryCount": 18,
                    "citationCoverageRate": 88.8,
                    "refusalRate": 11.1,
                    "hitRate": 86.2,
                    "firstTokenLatencyMs": 420,
                },
                "recentTasks": [
                    {
                        "id": "task-1",
                        "taskType": "parse_document_task",
                        "status": "FAILED",
                        "stage": "PARSING",
                        "requestId": "req_failed",
                        "createdAt": "2026-07-05T10:00:00+08:00",
                    }
                ],
                "riskEvents": [
                    {
                        "type": "TASK_FAILED",
                        "severity": "HIGH",
                        "message": "PARSER_UNAVAILABLE",
                        "requestId": "req_failed",
                        "createdAt": "2026-07-05T10:00:00+08:00",
                    }
                ],
            },
        )
        return

    if method == "GET" and path == "/api/v1/logs/task-runs":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "task-run-1",
                        "taskType": "parse_document_task",
                        "queueName": "parse",
                        "resourceType": "IMPORT_JOB",
                        "resourceId": "job-1",
                        "stage": "PARSING",
                        "status": "FAILED",
                        "error": {"code": "PARSER_UNAVAILABLE"},
                        "errorCode": "PARSER_UNAVAILABLE",
                        "errorSummary": "解析器不可用",
                        "retryable": True,
                        "requestId": "req_failed",
                        "createdAt": "2026-07-05T10:00:00+08:00",
                        "updatedAt": "2026-07-05T10:01:00+08:00",
                    }
                ],
                "pagination": {"page": 1, "pageSize": 20, "totalItems": 1, "totalPages": 1},
            },
        )
        return

    if method == "GET" and path == "/api/v1/logs/model-calls":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "model-log-1",
                        "providerId": "provider-1",
                        "providerName": "OpenAI",
                        "modelConfigId": "model-1",
                        "modelName": "gpt-5",
                        "runId": "run-1",
                        "capability": "CHAT",
                        "status": "SUCCESS",
                        "latencyMs": 680,
                        "tokenUsage": {"total": 120},
                        "errorCode": None,
                        "errorMessage": None,
                        "requestId": "req_model",
                        "createdAt": "2026-07-05T10:00:00+08:00",
                    }
                ],
                "pagination": {"page": 1, "pageSize": 20, "totalItems": 2, "totalPages": 2},
            },
        )
        return

    if method == "GET" and path == "/api/v1/logs/api-calls":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "api-log-1",
                        "keyPrefix": "lx_live",
                        "path": "/v1/chat/completions",
                        "method": "POST",
                        "statusCode": 200,
                        "latencyMs": 142,
                        "errorCode": None,
                        "requestId": "req_api",
                        "requestMetadata": {},
                        "createdAt": "2026-07-05T10:00:00+08:00",
                    }
                ],
                "pagination": {"page": 1, "pageSize": 20, "totalItems": 2, "totalPages": 2},
            },
        )
        return

    if method == "GET" and path == "/api/v1/logs/audit":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "audit-log-1",
                        "actorId": "admin@lingxi.ai",
                        "action": "DOCUMENT_DELETE",
                        "resourceType": "DOCUMENT",
                        "resourceId": "doc-1",
                        "beforeSnapshot": {},
                        "afterSnapshot": None,
                        "requestId": "req_audit",
                        "createdAt": "2026-07-05T10:00:00+08:00",
                    }
                ],
                "pagination": {"page": 1, "pageSize": 20, "totalItems": 2, "totalPages": 2},
            },
        )
        return

    if method == "POST" and path == "/api/v1/task-runs/task-run-1/retry":
        fulfill_json(route, {"id": "task-run-1", "resourceId": "job-1", "status": "RUNNING", "stage": "PARSING", "retryCount": 2})
        return

    if method == "GET" and path == "/api/v1/settings":
        fulfill_json(route, SETTINGS)
        return

    if method == "PUT" and path == "/api/v1/settings":
        fulfill_json(route, SETTINGS)
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
    page.add_init_script(
        f"""
        localStorage.setItem('lingxi_access_token', 'playwright-token');
        localStorage.setItem('lingxi_user', JSON.stringify({json_dumps(AUTH_USER)}));
        """
    )
    return console_errors


def assert_no_overflow(page: Page, label: str) -> None:
    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1"):
        raise AssertionError(f"{label} 页面存在水平溢出")


def verify_release_pages(page: Page, suffix: str) -> list[str]:
    errors = prepare_page(page)

    page.goto(f"{APP_URL}/#dashboard", wait_until="networkidle")
    expect(page.get_by_role("heading", name="系统总览")).to_be_visible()
    expect(page.get_by_text("任务失败率")).to_be_visible()
    expect(page.get_by_text("PARSER_UNAVAILABLE")).to_be_visible()
    assert_no_overflow(page, "Dashboard")
    page.screenshot(path=str(SCREENSHOT_DIR / f"t17-dashboard-{suffix}.png"), full_page=True)

    page.goto(f"{APP_URL}/#logs?requestId=req_failed", wait_until="networkidle")
    expect(page.get_by_role("heading", name="日志与任务排障")).to_be_visible()
    expect(page.get_by_text("parse_document_task").first).to_be_visible()
    if suffix == "desktop":
        expect(page.get_by_role("columnheader", name="任务类型")).to_be_visible()
    expect(page.get_by_text("共 1 条 · 每页 20 条")).to_be_visible()
    page.get_by_role("button", name="详情").first.click()
    expect(page.get_by_role("dialog")).to_be_visible()
    page.get_by_role("button", name="关闭").click()
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="重试").first.click()
    for tab, row_text, first_column in [
        ("模型调用", "OpenAI", "模型服务"),
        ("API 调用", "POST /v1/chat/completions", "请求路径"),
        ("审计日志", "DOCUMENT_DELETE", "审计操作"),
    ]:
        page.get_by_role("button", name=tab).click()
        if suffix == "desktop":
            expect(page.get_by_role("columnheader", name=first_column)).to_be_visible()
        expect(page.get_by_text(row_text).first).to_be_visible()
        expect(page.get_by_text("共 2 条 · 每页 20 条")).to_be_visible()
        expect(page.get_by_role("button", name="下一页 ›")).to_be_visible()
    assert_no_overflow(page, "Logs")
    page.screenshot(path=str(SCREENSHOT_DIR / f"t17-logs-{suffix}.png"), full_page=True)

    page.goto(f"{APP_URL}/#settings", wait_until="networkidle")
    expect(page.get_by_role("heading", name="系统设置")).to_be_visible()
    page.get_by_label("最大文件大小 MB").fill("12")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="保存设置").click()
    expect(page.get_by_text("设置已保存")).to_be_visible()
    assert_no_overflow(page, "Settings")
    page.screenshot(path=str(SCREENSHOT_DIR / f"t17-settings-{suffix}.png"), full_page=True)

    return errors


def main() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        desktop_page = browser.new_page(viewport={"width": 1440, "height": 900})
        desktop_errors = verify_release_pages(desktop_page, "desktop")
        desktop_page.close()
        mobile_page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
        mobile_errors = verify_release_pages(mobile_page, "mobile")
        mobile_page.close()
        browser.close()

    all_errors = desktop_errors + mobile_errors
    if all_errors:
        raise AssertionError(f"浏览器控制台存在错误或警告: {all_errors}")
    print("T17 Playwright release acceptance passed")


if __name__ == "__main__":
    main()
