from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Route, expect, sync_playwright


APP_URL = "http://127.0.0.1:5174"

AUTH_USER = {
    "id": "playwright-admin",
    "email": "admin@lingxi.ai",
    "name": "管理员",
    "roles": ["系统管理员"],
    "permissions": [
        "API_KEY_READ",
        "MODEL_CONFIG_READ",
        "USER_READ",
        "USER_WRITE",
        "ROLE_READ",
        "ROLE_WRITE",
    ],
}


def json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)


def fulfill_json(route: Route, payload: dict, status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=json_dumps(payload))


def api_path(route: Route) -> str:
    parsed = urlparse(route.request.url)
    marker = "/api/v1"
    return parsed.path[parsed.path.index(marker) :] if marker in parsed.path else parsed.path


def mock_api(route: Route) -> None:
    path = api_path(route)
    method = route.request.method

    if method == "GET" and path == "/api/v1/api-keys":
        fulfill_json(route, {"data": []})
        return

    if method == "GET" and path == "/api/v1/api-call-logs":
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
                        "createdAt": "2026-07-29T10:00:00+08:00",
                    }
                ]
            },
        )
        return

    if method == "GET" and path == "/api/v1/model-providers":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "provider-1",
                        "providerType": "OPENAI_COMPATIBLE",
                        "name": "DeepSeek Gateway",
                        "baseUrl": "https://api.deepseek.com",
                        "status": "ACTIVE",
                        "config": {},
                        "secretConfigured": True,
                    }
                ]
            },
        )
        return

    if method == "GET" and path == "/api/v1/model-configs":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "model-1",
                        "providerId": "provider-1",
                        "capability": "CHAT",
                        "modelName": "knowledge-chat",
                        "embeddingDimension": None,
                        "maxTokens": 4096,
                        "timeoutMs": 30000,
                        "isDefault": True,
                        "status": "ACTIVE",
                        "config": {},
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
                        "id": "department-1",
                        "name": "产品研发部",
                        "code": "RD",
                        "parentId": None,
                        "userCount": 2,
                        "createdAt": "2026-07-29T09:00:00+08:00",
                    }
                ]
            },
        )
        return

    if method == "GET" and path == "/api/v1/roles":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "role-system-admin",
                        "name": "系统管理员",
                        "code": "SYSTEM_ADMIN",
                        "scope": "TENANT",
                        "isBuiltin": True,
                        "userCount": 1,
                        "permissionCount": 4,
                        "createdAt": "2026-07-29T09:00:00+08:00",
                    },
                    {
                        "id": "role-content-editor",
                        "name": "内容编辑",
                        "code": "CONTENT_EDITOR",
                        "scope": "TENANT",
                        "isBuiltin": False,
                        "userCount": 0,
                        "permissionCount": 2,
                        "createdAt": "2026-07-29T09:30:00+08:00",
                    },
                ],
                "pagination": {"page": 1, "pageSize": 20, "totalItems": 2, "totalPages": 1},
            },
        )
        return

    if method == "GET" and path == "/api/v1/roles/options":
        fulfill_json(
            route,
            {
                "data": [
                    {"id": "role-system-admin", "code": "SYSTEM_ADMIN", "name": "系统管理员"},
                    {"id": "role-content-editor", "code": "CONTENT_EDITOR", "name": "内容编辑"},
                ]
            },
        )
        return

    if method == "GET" and path == "/api/v1/roles/available-permissions":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "permission-role-read",
                        "code": "ROLE_READ",
                        "module": "ROLE",
                        "action": "READ",
                        "description": "查看角色",
                    },
                    {
                        "id": "permission-role-write",
                        "code": "ROLE_WRITE",
                        "module": "ROLE",
                        "action": "WRITE",
                        "description": "管理角色",
                    },
                    {
                        "id": "permission-user-read",
                        "code": "USER_READ",
                        "module": "USER",
                        "action": "READ",
                        "description": "查看用户",
                    },
                ]
            },
        )
        return

    if method == "GET" and path.startswith("/api/v1/roles/"):
        role_id = path.removeprefix("/api/v1/roles/")
        role = {
            "role-system-admin": {
                "id": "role-system-admin",
                "name": "系统管理员",
                "code": "SYSTEM_ADMIN",
                "scope": "TENANT",
                "isBuiltin": True,
                "userCount": 1,
                "permissionCount": 4,
                "createdAt": "2026-07-29T09:00:00+08:00",
                "permissions": [
                    {
                        "id": "permission-role-read",
                        "code": "ROLE_READ",
                        "module": "ROLE",
                        "action": "READ",
                        "description": "查看角色",
                    },
                    {
                        "id": "permission-role-write",
                        "code": "ROLE_WRITE",
                        "module": "ROLE",
                        "action": "WRITE",
                        "description": "管理角色",
                    },
                ],
            },
            "role-content-editor": {
                "id": "role-content-editor",
                "name": "内容编辑",
                "code": "CONTENT_EDITOR",
                "scope": "TENANT",
                "isBuiltin": False,
                "userCount": 0,
                "permissionCount": 2,
                "createdAt": "2026-07-29T09:30:00+08:00",
                "permissions": [
                    {
                        "id": "permission-role-read",
                        "code": "ROLE_READ",
                        "module": "ROLE",
                        "action": "READ",
                        "description": "查看角色",
                    },
                    {
                        "id": "permission-user-read",
                        "code": "USER_READ",
                        "module": "USER",
                        "action": "READ",
                        "description": "查看用户",
                    },
                ],
            },
        }.get(role_id)
        if role is not None:
            fulfill_json(route, role)
            return

    if method == "GET" and path == "/api/v1/users":
        fulfill_json(
            route,
            {
                "data": [
                    {
                        "id": "user-1",
                        "email": "lin.xiao@example.com",
                        "name": "林晓",
                        "status": "ACTIVE",
                        "departmentId": "department-1",
                        "departmentName": "产品研发部",
                        "roles": [{"id": "role-1", "code": "ADMIN", "name": "管理员"}],
                        "createdAt": "2026-07-29T09:00:00+08:00",
                    },
                    {
                        "id": "user-2",
                        "email": "chen.mo@example.com",
                        "name": "陈墨",
                        "status": "DISABLED",
                        "departmentId": None,
                        "departmentName": None,
                        "roles": [],
                        "createdAt": "2026-07-29T09:00:00+08:00",
                    },
                ],
                "pagination": {"page": 1, "pageSize": 20, "totalItems": 2, "totalPages": 2},
            },
        )
        return

    fulfill_json(route, {"error": {"code": "MOCK_NOT_FOUND", "message": path}}, 404)


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


def assert_management_actions(page: Page) -> None:
    edit = page.get_by_role("button", name="编辑").first
    delete = page.get_by_role("button", name="删除").first

    expect(edit).to_have_css("border-top-width", "0px")
    expect(delete).to_have_css("border-top-width", "0px")

    edit.hover()
    expect(edit).to_have_css("background-color", "rgb(234, 242, 255)")

    delete.hover()
    expect(delete).to_have_css("background-color", "rgb(255, 240, 241)")


def verify_admin_lists(page: Page, suffix: str) -> list[str]:
    errors = prepare_page(page)

    page.goto(f"{APP_URL}/#api-keys", wait_until="networkidle")
    expect(page.get_by_role("heading", name="调用日志")).to_be_visible()
    expect(page.get_by_text("POST", exact=True)).to_be_visible()
    expect(page.get_by_text("/v1/chat/completions", exact=True)).to_be_visible()
    if suffix == "desktop":
        expect(page.get_by_role("columnheader", name="请求路径")).to_be_visible()
    assert_no_overflow(page, "API Key")

    page.goto(f"{APP_URL}/#models", wait_until="networkidle")
    expect(page.get_by_role("heading", name="供应商列表")).to_be_visible()
    expect(page.get_by_role("heading", name="模型实例", exact=True)).to_be_visible()
    expect(page.get_by_label("供应商列表").get_by_text("DeepSeek Gateway", exact=True)).to_be_visible()
    if suffix == "desktop":
        expect(page.get_by_role("columnheader", name="供应商名称")).to_be_visible()
        expect(page.get_by_role("columnheader", name="模型名称")).to_be_visible()
    expect(page.get_by_role("button", name="编辑").first).to_be_visible()
    expect(page.get_by_role("button", name="删除").first).to_be_visible()
    assert_management_actions(page)
    assert_no_overflow(page, "模型配置")

    page.goto(f"{APP_URL}/#departments", wait_until="networkidle")
    expect(page.get_by_role("heading", name="部门列表")).to_be_visible()
    expect(page.get_by_text("产品研发部")).to_be_visible()
    if suffix == "desktop":
        expect(page.get_by_role("columnheader", name="部门名称")).to_be_visible()
    expect(page.get_by_role("button", name="编辑").first).to_be_visible()
    assert_no_overflow(page, "部门管理")

    page.goto(f"{APP_URL}/#users", wait_until="networkidle")
    expect(page.get_by_role("heading", name="用户列表")).to_be_visible()
    expect(page.get_by_text("lin.xiao@example.com")).to_be_visible()
    expect(page.get_by_text("共 2 人 · 每页 20 条")).to_be_visible()
    expect(page.get_by_role("button", name="1")).to_be_visible()
    if suffix == "desktop":
        expect(page.get_by_role("columnheader", name="用户")).to_be_visible()
    expect(page.get_by_role("button", name="编辑").first).to_be_visible()
    assert_no_overflow(page, "用户管理")

    page.goto(f"{APP_URL}/#roles", wait_until="networkidle")
    expect(page.get_by_role("heading", name="角色列表")).to_be_visible()
    expect(page.get_by_text("系统管理员", exact=True)).to_be_visible()
    expect(page.get_by_text("内置", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="查看").first).to_be_visible()
    expect(page.get_by_role("button", name="编辑").first).to_be_visible()
    if suffix == "desktop":
        expect(page.get_by_role("columnheader", name="角色")).to_be_visible()
    assert_no_overflow(page, "角色管理")

    return errors


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        desktop_page = browser.new_page(viewport={"width": 1440, "height": 900})
        desktop_errors = verify_admin_lists(desktop_page, "desktop")
        desktop_page.close()
        mobile_page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
        mobile_errors = verify_admin_lists(mobile_page, "mobile")
        mobile_page.close()
        browser.close()

    all_errors = desktop_errors + mobile_errors
    if all_errors:
        raise AssertionError(f"浏览器控制台存在错误或警告: {all_errors}")
    print("T18 admin list visual acceptance passed")


if __name__ == "__main__":
    main()
