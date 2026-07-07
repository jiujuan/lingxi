from sqlalchemy import select

from server.tests.test_auth_rbac import build_test_client


def login_admin(client) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "Admin123!"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def test_model_provider_secret_is_encrypted_and_never_returned():
    client, SessionLocal = build_test_client()
    headers = login_admin(client)

    response = client.post(
        "/api/v1/model-providers",
        headers=headers,
        json={
            "providerType": "OPENAI_COMPATIBLE",
            "name": "DeepSeek Gateway",
            "baseUrl": "mock://success",
            "apiKey": "sk-local-secret",
            "status": "ACTIVE",
            "config": {"organization": "ops"},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["secretConfigured"] is True
    assert "apiKey" not in body
    assert "sk-local-secret" not in response.text

    from server.app.models.model_config import ModelProvider

    with SessionLocal() as session:
        provider = session.get(ModelProvider, body["id"])

    assert provider is not None
    assert provider.encrypted_api_key
    assert provider.encrypted_api_key != "sk-local-secret"
    assert "sk-local-secret" not in provider.encrypted_api_key

    listed = client.get("/api/v1/model-providers", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["data"][0]["secretConfigured"] is True
    assert "sk-local-secret" not in listed.text


def test_model_provider_connection_test_writes_masked_call_log():
    client, SessionLocal = build_test_client()
    headers = login_admin(client)

    provider = client.post(
        "/api/v1/model-providers",
        headers=headers,
        json={
            "providerType": "OPENAI_COMPATIBLE",
            "name": "Mock Provider",
            "baseUrl": "mock://success",
            "apiKey": "sk-connection-secret",
            "status": "ACTIVE",
        },
    ).json()

    response = client.post(
        f"/api/v1/model-providers/{provider['id']}/connection-tests",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["status"] == "SUCCESS"
    assert "sk-connection-secret" not in response.text

    from server.app.models.model_config import ModelCallLog

    with SessionLocal() as session:
        logs = session.scalars(select(ModelCallLog)).all()

    assert len(logs) == 1
    assert logs[0].provider_id == provider["id"]
    assert logs[0].status == "SUCCESS"
    assert logs[0].error_message is None


def test_default_model_is_unique_per_capability():
    client, _ = build_test_client()
    headers = login_admin(client)

    provider = client.post(
        "/api/v1/model-providers",
        headers=headers,
        json={
            "providerType": "OPENAI_COMPATIBLE",
            "name": "Default Provider",
            "baseUrl": "mock://success",
            "apiKey": "sk-default-secret",
            "status": "ACTIVE",
        },
    ).json()
    first = client.post(
        "/api/v1/model-configs",
        headers=headers,
        json={
            "providerId": provider["id"],
            "capability": "CHAT",
            "modelName": "chat-a",
            "isDefault": True,
        },
    ).json()
    second = client.post(
        "/api/v1/model-configs",
        headers=headers,
        json={
            "providerId": provider["id"],
            "capability": "CHAT",
            "modelName": "chat-b",
            "isDefault": True,
        },
    ).json()

    listed = client.get("/api/v1/model-configs?capability=CHAT", headers=headers)
    assert listed.status_code == 200
    defaults = [item for item in listed.json()["data"] if item["isDefault"]]
    assert [item["id"] for item in defaults] == [second["id"]]

    response = client.patch(
        f"/api/v1/model-configs/{first['id']}/default",
        headers=headers,
    )
    assert response.status_code == 200

    listed = client.get("/api/v1/model-configs?capability=CHAT", headers=headers)
    defaults = [item for item in listed.json()["data"] if item["isDefault"]]
    assert [item["id"] for item in defaults] == [first["id"]]


def _create_provider(client, headers, name: str) -> dict:
    response = client.post(
        "/api/v1/model-providers",
        headers=headers,
        json={
            "providerType": "OPENAI_COMPATIBLE",
            "name": name,
            "baseUrl": "mock://success",
            "apiKey": "sk-secret",
            "status": "ACTIVE",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_provider_delete_blocked_until_models_are_removed():
    client, _ = build_test_client()
    headers = login_admin(client)

    provider = _create_provider(client, headers, "Deletable Provider")
    model = client.post(
        "/api/v1/model-configs",
        headers=headers,
        json={
            "providerId": provider["id"],
            "capability": "CHAT",
            "modelName": "chat-x",
            "isDefault": True,
        },
    ).json()

    blocked = client.delete(
        f"/api/v1/model-providers/{provider['id']}", headers=headers
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "PROVIDER_HAS_MODELS"

    deleted_model = client.delete(
        f"/api/v1/model-configs/{model['id']}", headers=headers
    )
    assert deleted_model.status_code == 200
    assert [
        item["id"] for item in client.get("/api/v1/model-configs", headers=headers).json()["data"]
    ] == []

    deleted = client.delete(
        f"/api/v1/model-providers/{provider['id']}", headers=headers
    )
    assert deleted.status_code == 200
    assert [
        item["id"]
        for item in client.get("/api/v1/model-providers", headers=headers).json()["data"]
    ] == []

    # Further operations on the soft-deleted rows behave like 404s.
    assert (
        client.delete(f"/api/v1/model-providers/{provider['id']}", headers=headers).status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/model-configs/{model['id']}", headers=headers).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/model-configs/{model['id']}",
            headers=headers,
            json={"modelName": "ghost"},
        ).status_code
        == 404
    )


def test_provider_and_model_update_via_patch():
    client, _ = build_test_client()
    headers = login_admin(client)

    provider = _create_provider(client, headers, "Patchable Provider")
    updated_provider = client.patch(
        f"/api/v1/model-providers/{provider['id']}",
        headers=headers,
        json={"name": "Renamed Provider", "baseUrl": "mock://renamed", "status": "DISABLED"},
    )
    assert updated_provider.status_code == 200
    assert updated_provider.json()["name"] == "Renamed Provider"
    assert updated_provider.json()["baseUrl"] == "mock://renamed"
    assert updated_provider.json()["status"] == "DISABLED"
    # Secret is untouched when apiKey is omitted from the PATCH.
    assert updated_provider.json()["secretConfigured"] is True

    model = client.post(
        "/api/v1/model-configs",
        headers=headers,
        json={
            "providerId": provider["id"],
            "capability": "EMBEDDING",
            "modelName": "embed-a",
            "isDefault": False,
        },
    ).json()
    updated_model = client.patch(
        f"/api/v1/model-configs/{model['id']}",
        headers=headers,
        json={"modelName": "embed-b", "timeoutMs": 60000, "embeddingDimension": 1024},
    )
    assert updated_model.status_code == 200
    assert updated_model.json()["modelName"] == "embed-b"
    assert updated_model.json()["timeoutMs"] == 60000
    assert updated_model.json()["embeddingDimension"] == 1024


def test_model_config_delete_requires_write_permission():
    client, _ = build_test_client()
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "employee@example.com", "password": "Employee123!"},
    )
    employee_headers = {"Authorization": f"Bearer {login.json()['accessToken']}"}

    assert (
        client.delete("/api/v1/model-providers/any-id", headers=employee_headers).status_code
        == 403
    )
    assert (
        client.delete("/api/v1/model-configs/any-id", headers=employee_headers).status_code
        == 403
    )
