import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Route, expect, sync_playwright


APP_URL = os.environ.get("LINGXI_ADMIN_APP_URL", "http://127.0.0.1:5174")

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


ROLE_PERMISSIONS = [
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


def initial_role_state() -> dict[str, dict]:
    permissions_by_id = {permission["id"]: permission for permission in ROLE_PERMISSIONS}

    def role(
        role_id: str,
        name: str,
        code: str,
        is_builtin: bool,
        user_count: int,
        permission_ids: list[str],
        created_at: str,
    ) -> dict:
        return {
            "id": role_id,
            "name": name,
            "code": code,
            "scope": "TENANT",
            "isBuiltin": is_builtin,
            "userCount": user_count,
            "permissionCount": len(permission_ids),
            "createdAt": created_at,
            "permissions": [permissions_by_id[permission_id] for permission_id in permission_ids],
        }

    return {
        "role-system-admin": role(
            "role-system-admin",
            "系统管理员",
            "SYSTEM_ADMIN",
            True,
            1,
            ["permission-role-read", "permission-role-write"],
            "2026-07-29T09:00:00+08:00",
        ),
        "role-content-editor": role(
            "role-content-editor",
            "内容编辑",
            "CONTENT_EDITOR",
            False,
            0,
            ["permission-role-read", "permission-user-read"],
            "2026-07-29T09:30:00+08:00",
        ),
    }


ROLE_STATE = initial_role_state()
ROLE_MUTATIONS: list[dict] = []
ROLE_LIST_REQUESTS = 0


def role_list_item(role: dict) -> dict:
    return {
        key: role[key]
        for key in (
            "id",
            "name",
            "code",
            "scope",
            "isBuiltin",
            "userCount",
            "permissionCount",
            "createdAt",
        )
    }


def apply_role_payload(role: dict, payload: dict) -> None:
    permissions_by_id = {permission["id"]: permission for permission in ROLE_PERMISSIONS}
    role["name"] = payload["name"]
    role["code"] = payload["code"]
    role["permissions"] = [
        permissions_by_id[permission_id]
        for permission_id in payload["permissionIds"]
        if permission_id in permissions_by_id
    ]
    role["permissionCount"] = len(role["permissions"])


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
        global ROLE_LIST_REQUESTS
        ROLE_LIST_REQUESTS += 1
        fulfill_json(
            route,
            {
                "data": [role_list_item(role) for role in ROLE_STATE.values()],
                "pagination": {
                    "page": 1,
                    "pageSize": 20,
                    "totalItems": len(ROLE_STATE),
                    "totalPages": 1,
                },
            },
        )
        return

    if method == "GET" and path == "/api/v1/roles/options":
        fulfill_json(
            route,
            {
                "data": [
                    {"id": role["id"], "code": role["code"], "name": role["name"]}
                    for role in ROLE_STATE.values()
                ]
            },
        )
        return

    if method == "GET" and path == "/api/v1/roles/available-permissions":
        fulfill_json(route, {"data": ROLE_PERMISSIONS})
        return

    if method == "POST" and path == "/api/v1/roles":
        payload = route.request.post_data_json
        ROLE_MUTATIONS.append({"method": method, "path": path, "payload": payload})
        if payload["code"] == "FAIL_ROLE":
            fulfill_json(
                route,
                {"error": {"code": "ROLE_CODE_EXISTS", "message": "角色编码已存在"}},
                409,
            )
            return
        role = {
            "id": f"role-{payload['code'].lower()}",
            "name": payload["name"],
            "code": payload["code"],
            "scope": "TENANT",
            "isBuiltin": False,
            "userCount": 0,
            "permissionCount": 0,
            "createdAt": "2026-07-30T10:00:00+08:00",
            "permissions": [],
        }
        apply_role_payload(role, payload)
        ROLE_STATE[role["id"]] = role
        fulfill_json(route, role, 201)
        return

    if method == "PUT" and path.startswith("/api/v1/roles/"):
        role_id = path.removeprefix("/api/v1/roles/")
        payload = route.request.post_data_json
        ROLE_MUTATIONS.append({"method": method, "path": path, "payload": payload})
        role = ROLE_STATE.get(role_id)
        if role is None:
            fulfill_json(route, {"error": {"code": "NOT_FOUND", "message": "角色不存在"}}, 404)
            return
        if payload["code"] == "FAIL_ROLE":
            fulfill_json(
                route,
                {"error": {"code": "ROLE_CODE_EXISTS", "message": "角色编码已存在"}},
                409,
            )
            return
        apply_role_payload(role, payload)
        fulfill_json(route, role)
        return

    if method == "GET" and path.startswith("/api/v1/roles/"):
        role_id = path.removeprefix("/api/v1/roles/")
        role = ROLE_STATE.get(role_id)
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
    global ROLE_LIST_REQUESTS, ROLE_MUTATIONS, ROLE_STATE
    ROLE_STATE = initial_role_state()
    ROLE_MUTATIONS = []
    ROLE_LIST_REQUESTS = 0
    console_errors: list[str] = []
    def record_console(message: object) -> None:
        message_type = getattr(message, "type", "")
        message_text = getattr(message, "text", "")
        if message_type not in {"error", "warning"}:
            return
        # The role-create failure case below intentionally returns HTTP 409 and Chromium
        # reports that expected response as a resource-load console error.
        if message_text == "Failed to load resource: the server responded with a status of 409 (Conflict)":
            return
        console_errors.append(message_text)

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
    built_in_row = page.get_by_role("row").filter(has_text="系统管理员")
    custom_role_row = page.get_by_role("row").filter(has_text="内容编辑")
    expect(built_in_row.get_by_role("button", name="查看")).to_be_visible()
    expect(built_in_row.get_by_role("button", name="编辑")).to_have_count(0)
    expect(custom_role_row.get_by_role("button", name="编辑")).to_be_visible()
    expect(custom_role_row.get_by_role("button", name="删除")).to_be_visible()
    built_in_row.get_by_role("button", name="查看").click()
    expect(page.get_by_role("heading", name="查看角色")).to_be_visible()
    page.get_by_role("button", name="关闭").click()

    roles_before_create = ROLE_LIST_REQUESTS
    page.get_by_role("button", name="新建角色").click()
    create_dialog = page.get_by_role("dialog", name="新增角色")
    expect(create_dialog).to_be_visible()
    create_dialog.get_by_label("名称").fill("  新建角色  ")
    create_dialog.get_by_label("编码").fill("content_admin")
    create_dialog.get_by_role("button", name="保存").click()
    expect(create_dialog).to_have_count(0)
    expect(page.get_by_role("row").filter(has_text="新建角色")).to_be_visible()
    assert ROLE_MUTATIONS[-1] == {
        "method": "POST",
        "path": "/api/v1/roles",
        "payload": {"name": "新建角色", "code": "CONTENT_ADMIN", "permissionIds": []},
    }
    assert ROLE_LIST_REQUESTS > roles_before_create, "新增后应刷新角色列表缓存"

    custom_role_row.get_by_role("button", name="编辑").click()
    edit_dialog = page.get_by_role("dialog", name="编辑角色")
    expect(edit_dialog).to_be_visible()
    edit_dialog.get_by_label("名称").fill("  内容主管  ")
    edit_dialog.get_by_label("编码").fill("content_owner")
    roles_before_update = ROLE_LIST_REQUESTS
    edit_dialog.get_by_role("button", name="保存").click()
    expect(edit_dialog).to_have_count(0)
    expect(page.get_by_role("row").filter(has_text="内容主管")).to_be_visible()
    assert ROLE_MUTATIONS[-1] == {
        "method": "PUT",
        "path": "/api/v1/roles/role-content-editor",
        "payload": {"name": "内容主管", "code": "CONTENT_OWNER", "permissionIds": ["permission-role-read", "permission-user-read"]},
    }
    assert ROLE_LIST_REQUESTS > roles_before_update, "编辑后应刷新角色列表缓存"

    updated_role_row = page.get_by_role("row").filter(has_text="内容主管")
    updated_role_row.get_by_role("button", name="编辑").click()
    failed_update_dialog = page.get_by_role("dialog", name="编辑角色")
    failed_update_dialog.get_by_label("编码").fill("fail_role")
    failed_update_dialog.get_by_role("button", name="保存").click()
    expect(failed_update_dialog).to_be_visible()
    expect(failed_update_dialog.get_by_text("角色编码已存在", exact=True)).to_be_visible()
    assert ROLE_MUTATIONS[-1] == {
        "method": "PUT",
        "path": "/api/v1/roles/role-content-editor",
        "payload": {"name": "内容主管", "code": "FAIL_ROLE", "permissionIds": ["permission-role-read", "permission-user-read"]},
    }
    failed_update_dialog.get_by_role("button", name="关闭").click()

    page.get_by_role("button", name="新建角色").click()
    failed_dialog = page.get_by_role("dialog", name="新增角色")
    failed_dialog.get_by_label("名称").fill("  失败角色  ")
    failed_dialog.get_by_label("编码").fill("fail_role")
    failed_dialog.get_by_role("button", name="保存").click()
    expect(failed_dialog).to_be_visible()
    expect(failed_dialog.get_by_text("角色编码已存在", exact=True)).to_be_visible()
    assert ROLE_MUTATIONS[-1] == {
        "method": "POST",
        "path": "/api/v1/roles",
        "payload": {"name": "失败角色", "code": "FAIL_ROLE", "permissionIds": []},
    }
    failed_dialog.get_by_role("button", name="关闭").click()

    page.evaluate(
        """() => {
          const nativeFetch = window.fetch.bind(window);
          let delayed = false;
          window.fetch = (...args) => {
            const [resource, init] = args;
            if (!delayed && String(resource).includes('/api/v1/roles') && init?.method === 'POST') {
              delayed = true;
              return new Promise((resolve) => window.setTimeout(() => resolve(nativeFetch(...args)), 350));
            }
            return nativeFetch(...args);
          };
        }"""
    )
    page.get_by_role("button", name="新建角色").click()
    saving_dialog = page.get_by_role("dialog", name="新增角色")
    saving_dialog.get_by_label("名称").fill("保存中角色")
    saving_dialog.get_by_label("编码").fill("slow_role")
    saving_dialog.get_by_role("button", name="保存").click()
    expect(saving_dialog.get_by_role("button", name="关闭")).to_be_disabled()
    page.locator(".modal-backdrop").click(position={"x": 2, "y": 2})
    expect(saving_dialog).to_be_visible()
    expect(saving_dialog).to_have_count(0)

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
