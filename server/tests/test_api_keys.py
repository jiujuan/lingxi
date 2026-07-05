from sqlalchemy import select

from server.tests.test_auth_rbac import build_test_client
from server.tests.test_model_config import login_admin


def test_api_key_create_lists_prefix_only_and_does_not_store_plaintext():
    from server.app.models.api_key import ApiKey
    from server.app.models.logs import AuditLog

    client, SessionLocal = build_test_client()
    headers = login_admin(client)

    created = client.post(
        "/api/v1/api-keys",
        headers=headers,
        json={
            "name": "Internal Copilot",
            "scopes": ["chat:read", "knowledge:query"],
            "allowedDepartmentIds": [],
            "allowedRoleIds": [],
            "rateLimitPerMinute": 2,
        },
    )

    assert created.status_code == 200
    body = created.json()
    assert body["key"].startswith("lk_live_")
    assert body["keyPrefix"] in body["key"]

    listed = client.get("/api/v1/api-keys", headers=headers)
    assert listed.status_code == 200
    assert "key" not in listed.json()["data"][0]
    assert listed.json()["data"][0]["keyPrefix"] == body["keyPrefix"]

    with SessionLocal() as session:
        api_key = session.scalar(select(ApiKey))
        audit = session.scalar(select(AuditLog).where(AuditLog.action == "API_KEY_CREATED"))

    assert api_key.key_hash != body["key"]
    assert body["key"] not in api_key.key_hash
    assert audit is not None


def test_api_key_auth_scope_rate_limit_disable_rotate_and_call_log():
    from server.app.models.api_key import ApiCallLog

    client, SessionLocal = build_test_client()
    headers = login_admin(client)
    created = client.post(
        "/api/v1/api-keys",
        headers=headers,
        json={
            "name": "Limited",
            "scopes": ["chat:read"],
            "rateLimitPerMinute": 1,
        },
    ).json()
    key = created["key"]
    auth = {"Authorization": f"Bearer {key}"}

    ok = client.get("/api/v1/api-key-auth/probe?scope=chat:read", headers=auth)
    assert ok.status_code == 200
    assert ok.json()["keyPrefix"] == created["keyPrefix"]

    limited = client.get("/api/v1/api-key-auth/probe?scope=chat:read", headers=auth)
    assert limited.status_code == 429

    forbidden = client.get("/api/v1/api-key-auth/probe?scope=knowledge:query", headers=auth)
    assert forbidden.status_code == 403

    disabled = client.post(
        f"/api/v1/api-keys/{created['id']}/disable", headers=headers
    )
    assert disabled.status_code == 200
    invalid_after_disable = client.get("/api/v1/api-key-auth/probe?scope=chat:read", headers=auth)
    assert invalid_after_disable.status_code == 401

    rotated = client.post(
        f"/api/v1/api-keys/{created['id']}/rotations", headers=headers
    )
    assert rotated.status_code == 200
    assert rotated.json()["key"] != key
    assert rotated.json()["key"].startswith("lk_live_")

    old_key = client.get("/api/v1/api-key-auth/probe?scope=chat:read", headers=auth)
    assert old_key.status_code == 401

    with SessionLocal() as session:
        logs = session.scalars(select(ApiCallLog)).all()

    assert logs
    assert all(log.key_prefix == created["keyPrefix"] for log in logs)
    assert all("lk_live_" not in str(log.request_metadata) for log in logs)
