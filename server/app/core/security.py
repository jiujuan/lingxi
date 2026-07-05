from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from server.app.core.config import settings
from server.app.core.errors import unauthenticated


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_token(
    subject: str, token_type: str, expires_delta: timedelta, token_version: int
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "ver": token_version,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str, token_version: int) -> str:
    return create_token(
        subject=subject,
        token_type="access",
        expires_delta=timedelta(minutes=settings.access_token_minutes),
        token_version=token_version,
    )


def create_refresh_token(subject: str, token_version: int) -> str:
    return create_token(
        subject=subject,
        token_type="refresh",
        expires_delta=timedelta(minutes=settings.refresh_token_minutes),
        token_version=token_version,
    )


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
    except JWTError as exc:
        raise unauthenticated("Token 无效") from exc

    if payload.get("type") != expected_type:
        raise unauthenticated("Token 类型错误")
    return payload


def assert_token_current(payload: dict[str, Any], current_version: int) -> None:
    """Reject a token whose version no longer matches the user's.

    ``token_version`` is bumped on logout / password change / disable, which
    instantly revokes every token issued before the bump.
    """
    if payload.get("ver") != current_version:
        raise unauthenticated("Token 已失效")

