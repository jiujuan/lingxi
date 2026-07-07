from sqlalchemy import select

from server.tests.test_auth_rbac import build_test_client
from server.tests.test_model_config import login_admin


def login_employee(client) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "employee@example.com", "password": "Employee123!"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


# ---------------------------------------------------------------- departments


def test_department_crud_roundtrip_with_audit():
    from server.app.models.logs import AuditLog

    client, SessionLocal = build_test_client()
    headers = login_admin(client)

    created = client.post(
        "/api/v1/departments",
        headers=headers,
        json={"name": "研发中心", "code": "rd"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["code"] == "RD"  # normalized to upper case
    assert body["userCount"] == 0

    child = client.post(
        "/api/v1/departments",
        headers=headers,
        json={"name": "后端组", "code": "RD-BE", "parentId": body["id"]},
    )
    assert child.status_code == 200
    assert child.json()["parentId"] == body["id"]

    updated = client.put(
        f"/api/v1/departments/{child.json()['id']}",
        headers=headers,
        json={"name": "服务端组", "code": "RD-BE", "parentId": body["id"]},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "服务端组"

    listed = client.get("/api/v1/departments", headers=headers)
    assert listed.status_code == 200
    codes = {item["code"] for item in listed.json()["data"]}
    assert {"RD", "RD-BE", "SUPPORT", "PRIVATE"} <= codes

    deleted = client.delete(
        f"/api/v1/departments/{child.json()['id']}", headers=headers
    )
    assert deleted.status_code == 200

    with SessionLocal() as session:
        actions = set(
            session.scalars(
                select(AuditLog.action).where(AuditLog.resource_type == "DEPARTMENT")
            )
        )
    assert {"DEPARTMENT_CREATED", "DEPARTMENT_UPDATED", "DEPARTMENT_DELETED"} <= actions


def test_department_code_conflict_and_delete_guards():
    client, _ = build_test_client()
    headers = login_admin(client)

    parent = client.post(
        "/api/v1/departments", headers=headers, json={"name": "运营", "code": "OPS"}
    ).json()
    duplicated = client.post(
        "/api/v1/departments", headers=headers, json={"name": "运营2", "code": "OPS"}
    )
    assert duplicated.status_code == 409
    assert duplicated.json()["error"]["code"] == "DEPARTMENT_CODE_EXISTS"

    child = client.post(
        "/api/v1/departments",
        headers=headers,
        json={"name": "投放组", "code": "OPS-AD", "parentId": parent["id"]},
    ).json()

    blocked = client.delete(f"/api/v1/departments/{parent['id']}", headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "DEPARTMENT_HAS_CHILDREN"

    # A department with users cannot be deleted either.
    user = client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "email": "ops@example.com",
            "name": "Ops",
            "password": "OpsUser123!",
            "departmentId": child["id"],
        },
    )
    assert user.status_code == 200
    blocked = client.delete(f"/api/v1/departments/{child['id']}", headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "DEPARTMENT_HAS_USERS"


def test_department_parent_cannot_be_self_or_descendant():
    client, _ = build_test_client()
    headers = login_admin(client)

    top = client.post(
        "/api/v1/departments", headers=headers, json={"name": "总部", "code": "HQ"}
    ).json()
    mid = client.post(
        "/api/v1/departments",
        headers=headers,
        json={"name": "分部", "code": "HQ-SUB", "parentId": top["id"]},
    ).json()

    self_parent = client.put(
        f"/api/v1/departments/{top['id']}",
        headers=headers,
        json={"name": "总部", "code": "HQ", "parentId": top["id"]},
    )
    assert self_parent.status_code == 400

    cycle = client.put(
        f"/api/v1/departments/{top['id']}",
        headers=headers,
        json={"name": "总部", "code": "HQ", "parentId": mid["id"]},
    )
    assert cycle.status_code == 400
    assert cycle.json()["error"]["code"] == "DEPARTMENT_PARENT_INVALID"


# ---------------------------------------------------------------------- users


def test_user_crud_roundtrip_with_roles_and_filters():
    client, _ = build_test_client()
    headers = login_admin(client)

    roles = client.get("/api/v1/roles", headers=headers).json()["data"]
    employee_role = next(role for role in roles if role["code"] == "EMPLOYEE")
    departments = client.get("/api/v1/departments", headers=headers).json()["data"]
    support = next(item for item in departments if item["code"] == "SUPPORT")

    created = client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "email": "Zhang.San@Example.com",
            "name": "张三",
            "password": "ZhangSan123!",
            "departmentId": support["id"],
            "roleIds": [employee_role["id"]],
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["email"] == "zhang.san@example.com"  # normalized
    assert body["departmentName"] == "Support"
    assert [role["code"] for role in body["roles"]] == ["EMPLOYEE"]

    # New user can log in immediately.
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "zhang.san@example.com", "password": "ZhangSan123!"},
    )
    assert login.status_code == 200

    listed = client.get(
        "/api/v1/users",
        headers=headers,
        params={"keyword": "张三", "departmentId": support["id"]},
    )
    assert listed.status_code == 200
    assert listed.json()["pagination"]["totalItems"] == 1
    assert listed.json()["data"][0]["id"] == body["id"]

    updated = client.put(
        f"/api/v1/users/{body['id']}",
        headers=headers,
        json={
            "email": "zhang.san@example.com",
            "name": "张三丰",
            "departmentId": None,
            "roleIds": [],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "张三丰"
    assert updated.json()["roles"] == []
    assert updated.json()["departmentId"] is None

    deleted = client.delete(f"/api/v1/users/{body['id']}", headers=headers)
    assert deleted.status_code == 200
    assert client.get(
        "/api/v1/users", headers=headers, params={"keyword": "zhang.san"}
    ).json()["pagination"]["totalItems"] == 0


def test_user_duplicate_email_conflict():
    client, _ = build_test_client()
    headers = login_admin(client)

    duplicated = client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": "admin@example.com", "name": "冒名", "password": "Password123!"},
    )
    assert duplicated.status_code == 409
    assert duplicated.json()["error"]["code"] == "USER_EMAIL_EXISTS"


def test_disable_revokes_tokens_and_enable_restores_login():
    client, _ = build_test_client()
    admin_headers = login_admin(client)
    employee_headers = login_employee(client)

    users = client.get(
        "/api/v1/users", headers=admin_headers, params={"keyword": "employee"}
    ).json()["data"]
    employee_id = users[0]["id"]

    disabled = client.post(
        f"/api/v1/users/{employee_id}/disable", headers=admin_headers
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "DISABLED"

    # Outstanding token is revoked and login is rejected.
    me = client.get("/api/v1/auth/me", headers=employee_headers)
    assert me.status_code == 401
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "employee@example.com", "password": "Employee123!"},
    )
    assert login.status_code in (401, 403)

    enabled = client.post(
        f"/api/v1/users/{employee_id}/enable", headers=admin_headers
    )
    assert enabled.status_code == 200
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "employee@example.com", "password": "Employee123!"},
    )
    assert login.status_code == 200


def test_reset_password_revokes_old_sessions():
    client, _ = build_test_client()
    admin_headers = login_admin(client)
    employee_headers = login_employee(client)

    users = client.get(
        "/api/v1/users", headers=admin_headers, params={"keyword": "employee"}
    ).json()["data"]
    employee_id = users[0]["id"]

    reset = client.post(
        f"/api/v1/users/{employee_id}/password",
        headers=admin_headers,
        json={"password": "NewEmployee123!"},
    )
    assert reset.status_code == 200

    assert client.get("/api/v1/auth/me", headers=employee_headers).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "employee@example.com", "password": "Employee123!"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "employee@example.com", "password": "NewEmployee123!"},
        ).status_code
        == 200
    )


def test_admin_cannot_disable_or_delete_self():
    client, _ = build_test_client()
    headers = login_admin(client)

    me = client.get("/api/v1/auth/me", headers=headers).json()

    disabled = client.post(f"/api/v1/users/{me['id']}/disable", headers=headers)
    assert disabled.status_code == 400
    assert disabled.json()["error"]["code"] == "CANNOT_DISABLE_SELF"

    deleted = client.delete(f"/api/v1/users/{me['id']}", headers=headers)
    assert deleted.status_code == 400
    assert deleted.json()["error"]["code"] == "CANNOT_DELETE_SELF"


def test_org_endpoints_require_permissions():
    client, _ = build_test_client()
    employee_headers = login_employee(client)

    assert client.get("/api/v1/users", headers=employee_headers).status_code == 403
    assert (
        client.get("/api/v1/departments", headers=employee_headers).status_code == 403
    )
    assert (
        client.post(
            "/api/v1/departments",
            headers=employee_headers,
            json={"name": "x", "code": "X"},
        ).status_code
        == 403
    )
    assert client.get("/api/v1/users").status_code == 401
