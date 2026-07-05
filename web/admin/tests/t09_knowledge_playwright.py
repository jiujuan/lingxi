from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Route, expect, sync_playwright


ROOT = Path(__file__).resolve().parents[3]
SCREENSHOT_DIR = ROOT / "docs" / "development" / "v1.1" / "acceptance"
APP_URL = "http://127.0.0.1:5174/#knowledge"


READY_DOCUMENT = {
    "id": "doc-ready",
    "title": "Refund SOP",
    "fileName": "refund.md",
    "fileType": "MARKDOWN",
    "mimeType": "text/markdown",
    "fileSize": 120,
    "status": "READY",
    "parserName": "LIGHTWEIGHT",
    "parserVersion": "1.0",
    "pageCount": 2,
    "qaPairCount": 1,
    "chunkCount": 1,
    "objectKey": "uploads/refund.md",
    "checksum": "sha256:refund",
    "permissions": {
        "allAuthenticated": True,
        "departments": [],
        "roles": [],
        "users": [],
    },
    "latestJob": {
        "id": "job-ready",
        "status": "COMPLETED",
        "stage": "COMPLETED",
        "progress": 100,
        "retryCount": 0,
        "errorCode": None,
        "errorMessage": None,
        "failedStage": None,
        "retryable": False,
    },
    "lastErrorCode": None,
    "lastErrorMessage": None,
    "processingLogs": [
        {
            "id": "task-ready",
            "taskType": "embed_qa_pairs_task",
            "queueName": "embedding",
            "stage": "EMBEDDING",
            "status": "SUCCESS",
            "error": None,
            "requestId": "req_ready",
        }
    ],
    "createdAt": "2026-07-05T10:00:00+08:00",
    "updatedAt": "2026-07-05T10:10:00+08:00",
}

FAILED_DOCUMENT = {
    **READY_DOCUMENT,
    "id": "doc-failed",
    "title": "Broken Manual",
    "fileName": "broken.pdf",
    "fileType": "PDF",
    "mimeType": "application/pdf",
    "fileSize": 300,
    "status": "FAILED",
    "parserName": None,
    "parserVersion": None,
    "pageCount": None,
    "qaPairCount": 0,
    "chunkCount": 0,
    "objectKey": "uploads/broken.pdf",
    "checksum": "sha256:broken",
    "permissions": {
        "allAuthenticated": False,
        "departments": [{"id": "dept-support", "name": "Support"}],
        "roles": [],
        "users": [],
    },
    "latestJob": {
        "id": "job-failed",
        "status": "FAILED",
        "stage": "PARSING",
        "progress": 20,
        "retryCount": 1,
        "errorCode": "PARSER_UNAVAILABLE",
        "errorMessage": "MinerU 解析器尚未配置",
        "failedStage": "PARSING",
        "retryable": True,
    },
    "lastErrorCode": "PARSER_UNAVAILABLE",
    "lastErrorMessage": "MinerU 解析器尚未配置",
    "processingLogs": [
        {
            "id": "task-failed",
            "taskType": "parse_document_task",
            "queueName": "parse",
            "stage": "PARSING",
            "status": "FAILED",
            "error": {
                "code": "PARSER_UNAVAILABLE",
                "message": "MinerU 解析器尚未配置",
                "retryable": True,
            },
            "requestId": "req_failed_parse",
        }
    ],
    "updatedAt": "2026-07-05T10:20:00+08:00",
}


def fulfill_json(route: Route, payload: dict, status: int = 200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json_dumps(payload),
    )


def json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)


def api_path(route: Route) -> str:
    parsed = urlparse(route.request.url)
    path = parsed.path
    marker = "/api/v1"
    if marker in path:
        return path[path.index(marker) :]
    return path


def mock_api(route: Route) -> None:
    request = route.request
    path = api_path(route)
    method = request.method

    if method == "GET" and path == "/api/v1/documents":
        fulfill_json(
            route,
            {
                "data": [READY_DOCUMENT, FAILED_DOCUMENT],
                "pagination": {
                    "page": 1,
                    "pageSize": 20,
                    "totalItems": 2,
                    "totalPages": 1,
                },
            },
        )
        return

    if method == "GET" and path == "/api/v1/documents/doc-ready":
        fulfill_json(route, READY_DOCUMENT)
        return

    if method == "GET" and path == "/api/v1/documents/doc-failed":
        fulfill_json(route, FAILED_DOCUMENT)
        return

    if method == "GET" and path == "/api/v1/documents/doc-ready/chunks":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "chunk-ready",
                        "documentId": "doc-ready",
                        "chunkIndex": 0,
                        "titlePath": ["退款流程"],
                        "content": "退款需要主管审批。",
                        "pageNo": 1,
                        "tokenCount": 4,
                        "sourceLocator": {"lineStart": 1},
                        "status": "ACTIVE",
                    }
                ],
                "pagination": {
                    "page": 1,
                    "pageSize": 20,
                    "totalItems": 1,
                    "totalPages": 1,
                },
            },
        )
        return

    if method == "GET" and path == "/api/v1/documents/doc-failed/chunks":
        fulfill_json(
            route,
            {
                "data": [],
                "pagination": {
                    "page": 1,
                    "pageSize": 20,
                    "totalItems": 0,
                    "totalPages": 0,
                },
            },
        )
        return

    if method == "GET" and path == "/api/v1/documents/doc-ready/qa-pairs":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "qa-ready",
                        "documentId": "doc-ready",
                        "chunkId": "chunk-ready",
                        "question": "退款需要谁审批？",
                        "answer": "退款需要主管审批。",
                        "quote": "退款需要主管审批。",
                        "pageNo": 1,
                        "embeddingStatus": "READY",
                        "status": "ACTIVE",
                    }
                ],
                "pagination": {
                    "page": 1,
                    "pageSize": 20,
                    "totalItems": 1,
                    "totalPages": 1,
                },
            },
        )
        return

    if method == "GET" and path == "/api/v1/documents/doc-failed/qa-pairs":
        fulfill_json(route, {"data": [], "pagination": {"page": 1, "pageSize": 20, "totalItems": 0, "totalPages": 0}})
        return

    if method == "PATCH" and path.endswith("/permissions"):
        fulfill_json(route, READY_DOCUMENT["permissions"])
        return

    if method == "DELETE" and path.startswith("/api/v1/documents/"):
        fulfill_json(route, {"id": path.rsplit("/", 1)[-1], "status": "DELETED"})
        return

    if method == "POST" and path == "/api/v1/import-jobs/job-failed/retries":
        fulfill_json(
            route,
            {
                "id": "job-failed",
                "documentId": "doc-failed",
                "status": "RUNNING",
                "stage": "PARSING",
                "progress": 20,
                "retryCount": 2,
                "errorCode": None,
                "errorMessage": None,
                "failedStage": None,
                "retryable": False,
                "file": None,
            },
        )
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


def verify_knowledge_page(page: Page, screenshot_name: str) -> list[str]:
    errors = prepare_page(page)
    page.goto(APP_URL, wait_until="networkidle")

    expect(page.get_by_role("heading", name="文档入库、权限和 QA 结果")).to_be_visible()
    expect(page.get_by_text("Refund SOP").first).to_be_visible()
    expect(page.get_by_text("Broken Manual").first).to_be_visible()
    expect(page.get_by_text("退款需要主管审批。").first).to_be_visible()
    expect(page.get_by_text("QA 对").first).to_be_visible()
    expect(page.get_by_text("处理日志").first).to_be_visible()

    page.get_by_role("button", name="权限").first.click()
    expect(page.get_by_role("dialog")).to_be_visible()
    page.get_by_role("button", name="关闭").click()

    page.get_by_role("button", name="Broken Manual").click()
    expect(page.get_by_text("PARSER_UNAVAILABLE").first).to_be_visible()
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="重试失败阶段").click()
    expect(page.get_by_text("PARSING").first).to_be_visible()

    overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
    if overflow:
        raise AssertionError("页面存在水平溢出")

    local_overflows = page.evaluate(
        """
        Array.from(document.querySelectorAll('.panel, .document-table, .filter-grid, .pagination-row'))
          .filter((element) => element.scrollWidth > element.clientWidth + 1)
          .map((element) => ({
            className: element.className,
            scrollWidth: element.scrollWidth,
            clientWidth: element.clientWidth
          }))
        """
    )
    if local_overflows:
        raise AssertionError(f"关键容器存在局部水平溢出: {local_overflows}")

    page.screenshot(path=str(SCREENSHOT_DIR / screenshot_name), full_page=True)
    return errors


def main() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        desktop_page = browser.new_page(viewport={"width": 1440, "height": 900})
        desktop_errors = verify_knowledge_page(desktop_page, "t09-knowledge-desktop.png")
        desktop_page.close()

        mobile_page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
        mobile_errors = verify_knowledge_page(mobile_page, "t09-knowledge-mobile.png")
        mobile_page.close()
        browser.close()

    all_errors = desktop_errors + mobile_errors
    if all_errors:
        raise AssertionError(f"浏览器控制台存在错误或警告: {all_errors}")

    print("T09 Playwright acceptance passed")
    print(f"desktop={SCREENSHOT_DIR / 't09-knowledge-desktop.png'}")
    print(f"mobile={SCREENSHOT_DIR / 't09-knowledge-mobile.png'}")


if __name__ == "__main__":
    main()
