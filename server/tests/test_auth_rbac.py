from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def build_test_client():
    from server.app.db.base import Base
    from server.app.db.session import get_db
    from server.app.main import create_app
    from server.app.services.seed_service import seed_identity_data

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        seed_identity_data(session)

    app = create_app()

    def override_get_db():
        with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), SessionLocal


def test_admin_can_login_and_fetch_current_user_permissions():
    client, _ = build_test_client()

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "Admin123!"},
    )

    assert login.status_code == 200
    body = login.json()
    assert body["accessToken"]
    assert body["refreshToken"]
    assert body["user"]["email"] == "admin@example.com"
    assert "DOCUMENT_READ" in body["user"]["permissions"]
    assert "DOCUMENT_PERMISSION_WRITE" in body["user"]["permissions"]

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['accessToken']}"},
    )

    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"
    assert "SYSTEM_ADMIN" in me.json()["roles"]


def test_password_hash_is_not_stored_as_plaintext():
    _, SessionLocal = build_test_client()

    from server.app.models.user import User

    with SessionLocal() as session:
        admin = session.scalar(select(User).where(User.email == "admin@example.com"))

    assert admin is not None
    assert admin.password_hash != "Admin123!"
    assert admin.password_hash.startswith("$2b$")


def test_protected_endpoint_returns_403_when_permission_is_missing():
    client, _ = build_test_client()

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "employee@example.com", "password": "Employee123!"},
    )
    assert login.status_code == 200

    response = client.get(
        "/api/v1/auth/permission-check?permission=DOCUMENT_DELETE",
        headers={"Authorization": f"Bearer {login.json()['accessToken']}"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_refresh_and_logout_endpoints_are_available():
    client, _ = build_test_client()

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "Admin123!"},
    )
    refresh_token = login.json()["refreshToken"]

    refreshed = client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": refresh_token},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["accessToken"]
    assert refreshed.json()["refreshToken"]

    logout = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {refreshed.json()['accessToken']}"},
    )
    assert logout.status_code == 200
    assert logout.json() == {"ok": True}
