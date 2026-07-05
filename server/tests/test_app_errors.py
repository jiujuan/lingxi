from fastapi import Request
from fastapi.testclient import TestClient

from server.tests.test_auth_rbac import build_test_client


def test_validation_error_uses_uniform_error_envelope():
    client, _ = build_test_client()
    # Missing required fields on login -> RequestValidationError (422).
    response = client.post("/api/v1/auth/login", json={})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "errors" in body["error"]["details"]
    assert body["requestId"]


def test_unhandled_exception_returns_500_envelope_without_stack():
    client, _ = build_test_client()
    app = client.app

    @app.get("/boom")
    def boom(_request: Request):  # noqa: ANN202
        raise RuntimeError("secret internal detail")

    # raise_server_exceptions=False so the registered 500 handler runs.
    with TestClient(app, raise_server_exceptions=False) as raw:
        response = raw.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "secret internal detail" not in response.text  # no stack/detail leak
    assert body["requestId"]


def test_cors_headers_present_for_allowed_origin():
    client, _ = build_test_client()
    response = client.get(
        "/health",
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
