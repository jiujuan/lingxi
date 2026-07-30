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


def test_existing_seed_role_repair_does_not_commit_caller_work():
    from server.app.db.base import Base
    from server.app.models.role import Role
    from server.app.models.user import Department
    from server.app.services.seed_service import seed_identity_data

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        identity = seed_identity_data(session)
        employee_role = identity["roles"]["employee"]
        employee_role.is_builtin = False
        session.commit()

    with SessionLocal() as session:
        tenant = seed_identity_data(session)["tenant"]
        session.add(
            Department(tenant_id=tenant.id, name="Pending", code="PENDING")
        )
        assert session.scalar(
            select(Role.is_builtin).where(Role.code == "EMPLOYEE")
        ) is True
        session.rollback()

    with SessionLocal() as session:
        assert session.scalar(
            select(Role.is_builtin).where(Role.code == "EMPLOYEE")
        ) is False
        assert session.scalar(
            select(Department).where(Department.code == "PENDING")
        ) is None

    with SessionLocal() as session:
        seed_identity_data(session)
        session.commit()

    with SessionLocal() as session:
        assert session.scalar(
            select(Role.is_builtin).where(Role.code == "EMPLOYEE")
        ) is True


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


def test_logout_revokes_outstanding_access_and_refresh_tokens():
    client, _ = build_test_client()

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "Admin123!"},
    ).json()
    access = login["accessToken"]
    refresh_token = login["refreshToken"]

    # token works before logout
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}).status_code == 200

    logout = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {access}"})
    assert logout.status_code == 200

    # the same access token is now revoked (token_version bumped)
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 401

    # the paired refresh token is revoked too -> cannot mint new tokens
    refreshed = client.post("/api/v1/auth/refresh", json={"refreshToken": refresh_token})
    assert refreshed.status_code == 401


def test_token_with_wrong_audience_is_rejected():
    from datetime import UTC, datetime, timedelta

    from jose import jwt

    from server.app.core.config import settings

    client, _ = build_test_client()
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "Admin123!"},
    ).json()
    user_id = login["user"]["id"]

    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": user_id,
            "type": "access",
            "ver": 1,
            "iss": settings.jwt_issuer,
            "aud": "someone-else",  # wrong audience
            "iat": int(now.timestamp()),
            "exp": now + timedelta(minutes=5),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401
