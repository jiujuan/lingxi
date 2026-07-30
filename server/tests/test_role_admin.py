from server.tests.test_auth_rbac import build_test_client
from server.tests.test_model_config import login_admin


def test_role_list_detail_and_permission_catalog():
    client, _ = build_test_client()
    headers = login_admin(client)

    listed = client.get("/api/v1/roles", headers=headers)
    assert listed.status_code == 200
    admin = next(item for item in listed.json()["data"] if item["code"] == "SYSTEM_ADMIN")
    assert admin["isBuiltin"] is True
    assert admin["scope"] == "TENANT"
    assert admin["userCount"] >= 1
    assert admin["permissionCount"] > 0

    detail = client.get(f"/api/v1/roles/{admin['id']}", headers=headers)
    assert detail.status_code == 200
    assert {
        permission["code"] for permission in detail.json()["permissions"]
    } >= {"ROLE_READ", "ROLE_WRITE"}

    catalog = client.get("/api/v1/roles/available-permissions", headers=headers)
    assert catalog.status_code == 200
    assert any(item["code"] == "ROLE_READ" for item in catalog.json()["data"])


def test_custom_role_crud_and_delete_guards():
    client, _ = build_test_client()
    headers = login_admin(client)
    permissions = client.get(
        "/api/v1/roles/available-permissions", headers=headers
    ).json()["data"]
    role_read_id = next(item["id"] for item in permissions if item["code"] == "ROLE_READ")

    created = client.post(
        "/api/v1/roles",
        headers=headers,
        json={
            "name": "审计查看者",
            "code": "AUDIT_VIEWER",
            "permissionIds": [role_read_id],
        },
    )
    assert created.status_code == 200
    role = created.json()
    assert role["isBuiltin"] is False
    assert role_read_id in {permission["id"] for permission in role["permissions"]}

    duplicate = client.post(
        "/api/v1/roles",
        headers=headers,
        json={
            "name": "重复角色",
            "code": "audit_viewer",
            "permissionIds": [],
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "ROLE_CODE_EXISTS"

    updated = client.put(
        f"/api/v1/roles/{role['id']}",
        headers=headers,
        json={
            "name": "审计只读",
            "code": "AUDIT_VIEWER",
            "permissionIds": [],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "审计只读"

    builtin = next(
        item
        for item in client.get("/api/v1/roles", headers=headers).json()["data"]
        if item["isBuiltin"]
    )
    protected = client.put(
        f"/api/v1/roles/{builtin['id']}",
        headers=headers,
        json={
            "name": builtin["name"],
            "code": builtin["code"],
            "permissionIds": [],
        },
    )
    assert protected.status_code == 400
    assert protected.json()["error"]["code"] == "BUILTIN_ROLE_PROTECTED"

    builtin_delete = client.delete(
        f"/api/v1/roles/{builtin['id']}", headers=headers
    )
    assert builtin_delete.status_code == 400
    assert builtin_delete.json()["error"]["code"] == "BUILTIN_ROLE_PROTECTED"

    deletable = client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": "临时角色", "code": "TEMPORARY", "permissionIds": []},
    )
    assert deletable.status_code == 200
    deleted = client.delete(
        f"/api/v1/roles/{deletable.json()['id']}", headers=headers
    )
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    assigned_user = client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "email": "audit.user@example.com",
            "name": "Audit User",
            "password": "AuditUser123!",
            "roleIds": [role["id"]],
        },
    )
    assert assigned_user.status_code == 200
    blocked = client.delete(f"/api/v1/roles/{role['id']}", headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "ROLE_HAS_USERS"
    assert blocked.json()["error"]["message"] == "请先解除关联用户后再删除"


def test_role_endpoints_require_role_permissions():
    client, _ = build_test_client()
    employee_headers = {
        "Authorization": (
            "Bearer "
            + client.post(
                "/api/v1/auth/login",
                json={
                    "email": "employee@example.com",
                    "password": "Employee123!",
                },
            ).json()["accessToken"]
        )
    }

    assert client.get("/api/v1/roles", headers=employee_headers).status_code == 403
    assert (
        client.post(
            "/api/v1/roles",
            headers=employee_headers,
            json={"name": "无权创建", "code": "DENIED", "permissionIds": []},
        ).status_code
        == 403
    )
