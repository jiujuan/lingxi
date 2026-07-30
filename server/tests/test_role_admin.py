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
    # The system admin has one user but many permissions; a join that
    # multiplies association rows would incorrectly return a larger count.
    assert admin["userCount"] == 1
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
    assert client.get("/api/v1/roles/options", headers=employee_headers).status_code == 403
    assert (
        client.post(
            "/api/v1/roles",
            headers=employee_headers,
            json={"name": "无权创建", "code": "DENIED", "permissionIds": []},
        ).status_code
        == 403
    )


def test_role_rejects_blank_name_and_unknown_permissions():
    client, _ = build_test_client()
    headers = login_admin(client)

    blank_name = client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": "   ", "code": "BLANK_NAME", "permissionIds": []},
    )
    assert blank_name.status_code == 422

    trimmed_name = client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": "  名称已修剪  ", "code": "TRIMMED_NAME", "permissionIds": []},
    )
    assert trimmed_name.status_code == 200
    assert trimmed_name.json()["name"] == "名称已修剪"

    unknown_permission = client.post(
        "/api/v1/roles",
        headers=headers,
        json={
            "name": "无效权限角色",
            "code": "UNKNOWN_PERMISSION",
            "permissionIds": ["missing-permission-id"],
        },
    )
    assert unknown_permission.status_code == 400
    assert unknown_permission.json()["error"]["code"] == "PERMISSION_NOT_FOUND"


def test_role_operations_hide_other_tenant_roles():
    from server.app.models.role import Role
    from server.app.models.user import Tenant

    client, SessionLocal = build_test_client()
    headers = login_admin(client)

    with SessionLocal() as session:
        other_tenant = Tenant(name="Other Tenant")
        session.add(other_tenant)
        session.flush()
        other_role = Role(
            tenant_id=other_tenant.id,
            name="Other Tenant Role",
            code="OTHER_TENANT_ROLE",
        )
        session.add(other_role)
        session.commit()
        other_role_id = other_role.id

    assert client.get(f"/api/v1/roles/{other_role_id}", headers=headers).status_code == 404
    assert (
        client.put(
            f"/api/v1/roles/{other_role_id}",
            headers=headers,
            json={
                "name": "Attempted Update",
                "code": "OTHER_TENANT_ROLE",
                "permissionIds": [],
            },
        ).status_code
        == 404
    )
    assert client.delete(f"/api/v1/roles/{other_role_id}", headers=headers).status_code == 404


def test_role_database_integrity_conflicts_are_mapped(monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from server.app.repositories.role_repo import RoleRepository

    client, _ = build_test_client()
    headers = login_admin(client)

    monkeypatch.setattr(
        RoleRepository,
        "get_by_code",
        lambda _self, _tenant_id, _code: None,
    )
    create_conflict = client.post(
        "/api/v1/roles",
        headers=headers,
        json={
            "name": "数据库冲突",
            "code": "SYSTEM_ADMIN",
            "permissionIds": [],
        },
    )
    assert create_conflict.status_code == 409
    assert create_conflict.json()["error"]["code"] == "ROLE_CODE_EXISTS"
    assert create_conflict.json()["error"]["message"] == "该角色编码已存在"

    monkeypatch.undo()
    custom_role = client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": "可更新角色", "code": "UPDATABLE", "permissionIds": []},
    ).json()
    monkeypatch.setattr(
        RoleRepository,
        "get_by_code",
        lambda _self, _tenant_id, _code: None,
    )
    update_conflict = client.put(
        f"/api/v1/roles/{custom_role['id']}",
        headers=headers,
        json={
            "name": "更新后冲突",
            "code": "SYSTEM_ADMIN",
            "permissionIds": [],
        },
    )
    assert update_conflict.status_code == 409
    assert update_conflict.json()["error"]["code"] == "ROLE_CODE_EXISTS"
    assert update_conflict.json()["error"]["message"] == "该角色编码已存在"

    monkeypatch.undo()
    deletable_role = client.post(
        "/api/v1/roles",
        headers=headers,
        json={"name": "删除冲突", "code": "DELETE_CONFLICT", "permissionIds": []},
    ).json()

    def raise_integrity_error(_self, _role):
        raise IntegrityError("DELETE FROM roles", {}, RuntimeError("foreign key"))

    monkeypatch.setattr(RoleRepository, "delete_if_unassigned", raise_integrity_error)
    delete_conflict = client.delete(
        f"/api/v1/roles/{deletable_role['id']}", headers=headers
    )
    assert delete_conflict.status_code == 409
    assert delete_conflict.json()["error"]["code"] == "ROLE_HAS_USERS"
    assert delete_conflict.json()["error"]["message"] == "请先解除关联用户后再删除"


def test_role_options_are_unpaginated_and_tenant_scoped_for_user_assignment():
    from server.app.models.role import Role
    from server.app.models.user import Tenant

    client, SessionLocal = build_test_client()
    headers = login_admin(client)
    option_codes = {f"ASSIGNMENT_OPTION_{index:02d}" for index in range(25)}

    with SessionLocal() as session:
        tenant_id = (
            session.query(Role.tenant_id)
            .filter(Role.code == "SYSTEM_ADMIN")
            .scalar()
        )
        session.add_all(
            [
                Role(
                    tenant_id=tenant_id,
                    name=f"分配选项角色 {index}",
                    code=code,
                )
                for index, code in enumerate(sorted(option_codes))
            ]
        )
        other_tenant = Tenant(name="Role Options Other Tenant")
        session.add(other_tenant)
        session.flush()
        session.add(
            Role(
                tenant_id=other_tenant.id,
                name="跨租户角色",
                code="OTHER_TENANT_OPTION",
            )
        )
        session.commit()

    options = client.get("/api/v1/roles/options", headers=headers)
    assert options.status_code == 200
    option_data = options.json()["data"]
    assert option_codes <= {item["code"] for item in option_data}
    assert "OTHER_TENANT_OPTION" not in {item["code"] for item in option_data}
    assert all(set(item) == {"id", "code", "name"} for item in option_data)
    assert "pagination" not in options.json()

    paginated = client.get("/api/v1/roles", headers=headers)
    assert paginated.status_code == 200
    assert len(paginated.json()["data"]) == 20
    assert paginated.json()["pagination"]["totalItems"] >= len(option_codes) + 3
