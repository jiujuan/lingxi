import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Route, expect, sync_playwright


ROOT = Path(__file__).resolve().parents[3]
APP_URL = os.environ.get("LINGXI_ADMIN_APP_URL", "http://127.0.0.1:5174")
SCREENSHOT_DIR = ROOT / "docs" / "development" / "v1.1" / "acceptance" / "qa-split-long-running"

AUTH_USER = {
    "id": "playwright-admin",
    "email": "admin@lingxi.ai",
    "name": "管理员",
    "roles": ["系统管理员"],
    "permissions": ["LOG_READ", "MODEL_CONFIG_READ"],
}

MODEL_PROVIDER = {
    "id": "provider-qa",
    "providerType": "OPENAI_COMPATIBLE",
    "name": "QA Gateway",
    "baseUrl": "https://qa-gateway.example.test/v1",
    "status": "ACTIVE",
    "config": {},
    "secretConfigured": True,
}


def initial_model_config() -> dict:
    return {
        "id": "model-qa",
        "providerId": MODEL_PROVIDER["id"],
        "capability": "QA_SPLIT",
        "modelName": "qa-long-running-v1",
        "embeddingDimension": None,
        "maxTokens": 4096,
        "timeoutMs": 30000,
        "connectTimeoutMs": 5000,
        "writeTimeoutMs": 12000,
        "readIdleTimeoutMs": 180000,
        "overallTimeoutMs": 240000,
        "isDefault": True,
        "status": "ACTIVE",
        "config": {
            "displayName": "QA 长耗时模型",
            "modelType": "CHAT",
            "qaSplit": {
                "maxInputTokens": 4096,
                "reservedOutputTokens": 2048,
                "maxRetries": 1,
                "maxSplitDepth": 1,
            },
        },
    }


MODEL_CONFIG = initial_model_config()
CONFIG_PATCHES: list[dict] = []


def json_dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def fulfill_json(route: Route, payload: dict, status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=json_dumps(payload))


def api_path(route: Route) -> str:
    parsed = urlparse(route.request.url)
    marker = "/api/v1"
    return parsed.path[parsed.path.index(marker) :] if marker in parsed.path else parsed.path


def mock_api(route: Route) -> None:
    global MODEL_CONFIG

    path = api_path(route)
    method = route.request.method

    if method == "GET" and path == "/api/v1/model-providers":
        fulfill_json(route, {"data": [MODEL_PROVIDER]})
        return

    if method == "GET" and path == "/api/v1/model-configs":
        fulfill_json(route, {"data": [MODEL_CONFIG]})
        return

    if method == "PATCH" and path == f"/api/v1/model-configs/{MODEL_CONFIG['id']}":
        payload = route.request.post_data_json
        CONFIG_PATCHES.append(payload)
        MODEL_CONFIG = {
            **MODEL_CONFIG,
            **payload,
            "config": payload.get("config", MODEL_CONFIG["config"]),
        }
        fulfill_json(route, MODEL_CONFIG)
        return

    if method == "POST" and path == f"/api/v1/model-providers/{MODEL_PROVIDER['id']}/connection-tests":
        fulfill_json(
            route,
            {
                "success": False,
                "status": "FAILED",
                "latencyMs": 8000,
                "errorCode": "PROVIDER_INFERENCE_TIMEOUT",
                "errorMessage": "模型在读取空闲窗口内没有返回首 Token。",
                "providerName": MODEL_PROVIDER["name"],
                "providerType": MODEL_PROVIDER["providerType"],
                "modelConfigId": MODEL_CONFIG["id"],
                "modelName": MODEL_CONFIG["modelName"],
                "endpoint": "https://qa-gateway.example.test/v1/chat/completions",
                "timeoutMs": MODEL_CONFIG["overallTimeoutMs"],
                "timeoutPhase": "read",
            },
        )
        return

    if method == "GET" and path == "/api/v1/logs/task-runs":
        fulfill_json(
            route,
            {
                "data": [],
                "pagination": {"page": 1, "pageSize": 20, "totalItems": 0, "totalPages": 1},
            },
        )
        return

    if method == "GET" and path == "/api/v1/logs/model-calls":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "model-log-qa-1",
                        "providerId": MODEL_PROVIDER["id"],
                        "providerName": MODEL_PROVIDER["name"],
                        "modelConfigId": MODEL_CONFIG["id"],
                        "modelName": MODEL_CONFIG["modelName"],
                        "runId": "qa-run-20260804",
                        "capability": "QA_SPLIT",
                        "status": "FAILED",
                        "latencyMs": 8000,
                        "tokenUsage": {"input": 3800, "output": 0},
                        "batchId": "qa-batch-0007",
                        "batchIndex": "7/12",
                        "retryCount": 1,
                        "splitDepth": 1,
                        "inputCharCount": 14200,
                        "estimatedInputTokens": 3800,
                        "outputCharCount": 0,
                        "estimatedOutputTokens": 0,
                        "timeoutPhase": "read",
                        "endpoint": "https://qa-gateway.example.test/v1/chat/completions",
                        "modelNameSnapshot": "qa-long-running-v1",
                        "errorCode": "PROVIDER_INFERENCE_TIMEOUT",
                        "errorMessage": "读取空闲超时",
                        "requestId": "req-qa-timeout",
                        "createdAt": "2026-08-04T10:00:00+08:00",
                    }
                ],
                "pagination": {"page": 1, "pageSize": 20, "totalItems": 1, "totalPages": 1},
            },
        )
        return

    fulfill_json(route, {"error": {"code": "MOCK_NOT_FOUND", "message": path}}, 404)


def prepare_page(page: Page) -> list[str]:
    global MODEL_CONFIG, CONFIG_PATCHES
    MODEL_CONFIG = initial_model_config()
    CONFIG_PATCHES = []
    console_errors: list[str] = []

    def record_console(message: object) -> None:
        message_type = getattr(message, "type", "")
        if message_type in {"error", "warning"}:
            console_errors.append(getattr(message, "text", ""))

    page.on("console", record_console)
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


def verify_model_config(page: Page, suffix: str) -> None:
    page.goto(f"{APP_URL}/#models", wait_until="networkidle")
    expect(page.get_by_role("heading", name="模型配置")).to_be_visible()
    expect(page.get_by_label("供应商列表").get_by_text("QA Gateway", exact=True)).to_be_visible()
    expect(page.get_by_label("模型实例").get_by_text("QA 长耗时模型", exact=True)).to_be_visible()

    model_row = page.get_by_role("row").filter(has_text="QA 长耗时模型")
    model_row.get_by_role("button", name="编辑").click()
    dialog = page.get_by_role("dialog", name="编辑模型实例")
    expect(dialog).to_be_visible()

    connect_input = dialog.get_by_label("连接超时（毫秒）")
    write_input = dialog.get_by_label("请求写入超时（毫秒）")
    read_input = dialog.get_by_label("首 Token/读取空闲超时（毫秒）")
    overall_input = dialog.get_by_label("单次调用总超时（毫秒）")
    expect(connect_input).to_have_value("5000")
    expect(write_input).to_have_value("12000")
    expect(read_input).to_have_value("180000")
    expect(overall_input).to_have_value("240000")

    overall_input.fill("1000")
    dialog.get_by_role("button", name="保存", exact=True).click()
    expect(dialog.get_by_text("单次调用总超时不能小于首 Token/读取空闲超时。")).to_be_visible()
    assert CONFIG_PATCHES == [], "非法 overall timeout 不应发送 PATCH"

    connect_input.fill("3200")
    write_input.fill("4500")
    read_input.fill("6000")
    overall_input.fill("8000")
    dialog.get_by_label("QA 最大输入 Tokens").fill("3000")
    dialog.get_by_label("QA 输出预留 Tokens").fill("1200")
    dialog.get_by_label("QA Batch retry 次数").fill("2")
    dialog.get_by_label("QA 最大二分深度").fill("3")
    dialog.get_by_role("button", name="保存", exact=True).click()
    expect(dialog).to_have_count(0)
    assert CONFIG_PATCHES[-1] == {
        "modelName": "qa-long-running-v1",
        "timeoutMs": 30000,
        "connectTimeoutMs": 3200,
        "writeTimeoutMs": 4500,
        "readIdleTimeoutMs": 6000,
        "overallTimeoutMs": 8000,
        "isDefault": True,
        "status": "ACTIVE",
        "maxTokens": 4096,
        "config": {
            "displayName": "QA 长耗时模型",
            "modelType": "CHAT",
            "qaSplit": {
                "maxInputTokens": 3000,
                "reservedOutputTokens": 1200,
                "maxRetries": 2,
                "maxSplitDepth": 3,
            },
        },
    }

    page.get_by_role("button", name="测试连接").first.click()
    result = page.locator(".model-connection-result")
    expect(result).to_be_visible()
    expect(result).to_contain_text("QA Gateway")
    expect(result).to_contain_text("qa-long-running-v1")
    expect(result).to_contain_text("https://qa-gateway.example.test/v1/chat/completions")
    expect(result).to_contain_text("8 秒 · 读取超时")
    assert_no_overflow(page, f"模型配置-{suffix}")


def verify_model_logs(page: Page, suffix: str) -> None:
    page.goto(f"{APP_URL}/#logs", wait_until="networkidle")
    page.get_by_role("button", name="模型调用").click()
    expect(page.get_by_role("heading", name="模型调用", exact=True)).to_be_visible()
    expect(page.get_by_text("qa-batch-0007", exact=False)).to_have_count(0)
    expect(page.get_by_text("QA Gateway", exact=True)).to_be_visible()
    expect(page.get_by_text("qa-long-running-v1 · QA_SPLIT", exact=True)).to_be_visible()
    page.get_by_role("button", name="详情").click()

    drawer = page.locator(".log-detail-drawer")
    expect(drawer).to_be_visible()
    expect(drawer).to_contain_text("qa-run-20260804")
    expect(drawer).to_contain_text("qa-batch-0007")
    expect(drawer).to_contain_text("7/12")
    expect(drawer).to_contain_text("Retry count")
    expect(drawer).to_contain_text("Split depth")
    expect(drawer).to_contain_text("PROVIDER_INFERENCE_TIMEOUT")
    expect(drawer).to_contain_text("https://qa-gateway.example.test/v1/chat/completions")
    expect(drawer).not_to_contain_text("SECRET_PROMPT")
    expect(drawer).not_to_contain_text("这是不应进入日志的 Prompt")
    assert_no_overflow(page, f"模型日志-{suffix}")


def verify_page(page: Page, suffix: str) -> list[str]:
    console_errors = prepare_page(page)
    verify_model_config(page, suffix)
    verify_model_logs(page, suffix)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SCREENSHOT_DIR / f"t12-admin-{suffix}.png"), full_page=True)
    return console_errors


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        desktop_page = browser.new_page(viewport={"width": 1440, "height": 900})
        desktop_errors = verify_page(desktop_page, "desktop")
        desktop_page.close()
        mobile_page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
        mobile_errors = verify_page(mobile_page, "mobile")
        mobile_page.close()
        browser.close()

    all_errors = desktop_errors + mobile_errors
    if all_errors:
        raise AssertionError(f"浏览器控制台存在错误或警告: {all_errors}")
    print("T19 QA split timeout admin acceptance passed")


if __name__ == "__main__":
    main()
