from server.tests.test_auth_rbac import build_test_client
from server.tests.test_model_config import login_admin


def test_secret_values_do_not_appear_in_model_api_or_audit_responses():
    client, SessionLocal = build_test_client()
    headers = login_admin(client)

    provider = client.post(
        "/api/v1/model-providers",
        headers=headers,
        json={
            "providerType": "OPENAI_COMPATIBLE",
            "name": "Secret Provider",
            "baseUrl": "mock://success",
            "apiKey": "sk-release-secret",
            "status": "ACTIVE",
        },
    )
    assert provider.status_code == 201
    assert "sk-release-secret" not in provider.text

    api_key = client.post(
        "/api/v1/api-keys",
        headers=headers,
        json={
            "name": "Secret Client",
            "scopes": ["chat:completions"],
            "rateLimitPerMinute": 20,
        },
    ).json()

    from server.app.models.logs import ApiCallLog, AuditLog

    with SessionLocal() as session:
        tenant_id = _tenant_id(session)
        session.add(
            ApiCallLog(
                tenant_id=tenant_id,
                key_prefix=api_key["keyPrefix"],
                path="/v1/chat/completions",
                method="POST",
                status_code=401,
                latency_ms=1,
                error_code="INVALID_API_KEY",
                request_id="req_secret",
                request_metadata={"Authorization": f"Bearer {api_key['key']}"},
            )
        )
        session.add(
                AuditLog(
                    tenant_id=tenant_id,
                action="SECRET_TEST",
                resource_type="TEST",
                before_snapshot={"apiKey": api_key["key"]},
                after_snapshot={"secret": "sk-release-secret"},
                request_id="req_secret",
            )
        )
        session.commit()

    logs = client.get("/api/v1/logs/api-calls?requestId=req_secret", headers=headers)
    audit = client.get("/api/v1/logs/audit?requestId=req_secret", headers=headers)

    assert logs.status_code == 200
    assert audit.status_code == 200
    assert api_key["key"] not in logs.text
    assert api_key["key"] not in audit.text
    assert "sk-release-secret" not in audit.text
    assert "***REDACTED***" in logs.text
    assert "***REDACTED***" in audit.text


def test_object_key_path_traversal_and_windows_paths_are_rejected():
    from server.app.integrations.storage.base import validate_object_key

    unsafe_keys = [
        "../private.md",
        "uploads/../private.md",
        "/absolute/path.md",
        "C:/Users/admin/secret.md",
        "uploads\\private.md",
        "uploads//private.md",
    ]

    for key in unsafe_keys:
        try:
            validate_object_key(key)
        except ValueError:
            continue
        raise AssertionError(f"unsafe object_key accepted: {key}")

    assert validate_object_key("tenant/imports/refund.md") == "tenant/imports/refund.md"


def _tenant_id(session) -> str:
    from sqlalchemy import select

    from server.app.models.user import Tenant

    return session.scalar(select(Tenant.id))
