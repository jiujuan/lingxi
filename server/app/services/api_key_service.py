from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from server.app.core.api_key_security import (
    api_key_prefix,
    generate_api_key,
    hash_api_key,
    verify_api_key,
)
from server.app.core.errors import forbidden, not_found
from server.app.core.ids import current_request_id
from server.app.core.permissions import AccessContext
from server.app.models.api_key import ApiKey
from server.app.models.logs import AuditLog
from server.app.repositories.api_key_repo import ApiKeyRepository
from server.app.services.rate_limit_service import RateLimitExceeded, RateLimitService


@dataclass(frozen=True)
class ApiKeyAuthResult:
    api_key: ApiKey


class ApiKeyService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = ApiKeyRepository(session)
        self.rate_limiter = RateLimitService()

    def create_key(
        self,
        context: AccessContext,
        *,
        name: str,
        scopes: list[str],
        allowed_department_ids: list[str] | None,
        allowed_role_ids: list[str] | None,
        rate_limit_per_minute: int,
        expires_at=None,
    ) -> tuple[ApiKey, str]:
        plaintext, prefix = generate_api_key()
        api_key = ApiKey(
            tenant_id=context.tenant_id,
            name=name.strip(),
            key_prefix=prefix,
            key_hash=hash_api_key(plaintext),
            scopes=scopes,
            allowed_department_ids=allowed_department_ids or [],
            allowed_role_ids=allowed_role_ids or [],
            rate_limit_per_minute=rate_limit_per_minute,
            status="ACTIVE",
            expires_at=expires_at,
        )
        self.repo.add(api_key)
        self._audit(context, "API_KEY_CREATED", api_key, None)
        self.session.commit()
        return api_key, plaintext

    def list_keys(self, context: AccessContext) -> list[ApiKey]:
        return self.repo.list_for_tenant(context.tenant_id)

    def disable_key(self, context: AccessContext, key_id: str) -> ApiKey:
        api_key = self._get_key(context, key_id)
        before = self._public_dict(api_key)
        api_key.status = "DISABLED"
        self._audit(context, "API_KEY_DISABLED", api_key, before)
        self.session.commit()
        return api_key

    def rotate_key(self, context: AccessContext, key_id: str) -> tuple[ApiKey, str]:
        api_key = self._get_key(context, key_id)
        before = self._public_dict(api_key)
        plaintext, prefix = generate_api_key()
        api_key.key_prefix = prefix
        api_key.key_hash = hash_api_key(plaintext)
        api_key.status = "ACTIVE"
        api_key.last_used_at = None
        self._audit(context, "API_KEY_ROTATED", api_key, before)
        self.session.commit()
        return api_key, plaintext

    def authenticate(self, plaintext_key: str, required_scope: str | None = None) -> ApiKeyAuthResult:
        prefix = api_key_prefix(plaintext_key)
        if not prefix:
            raise self._unauthorized("INVALID_API_KEY", "API Key 无效")
        for candidate in self.repo.list_by_prefix(prefix):
            if verify_api_key(plaintext_key, candidate.key_hash):
                return self._validate_candidate(candidate, required_scope)
        raise self._unauthorized("INVALID_API_KEY", "API Key 无效")

    def _validate_candidate(
        self, api_key: ApiKey, required_scope: str | None
    ) -> ApiKeyAuthResult:
        if api_key.status != "ACTIVE":
            raise self._unauthorized("API_KEY_DISABLED", "API Key 已禁用")
        now = datetime.now(UTC)
        expires_at = api_key.expires_at
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at and expires_at < now:
            raise self._unauthorized("API_KEY_EXPIRED", "API Key 已过期")
        if required_scope and required_scope not in (api_key.scopes or []):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": {
                        "code": "API_KEY_FORBIDDEN",
                        "message": "API Key Scope 不足",
                        "details": {},
                    },
                    "requestId": current_request_id(),
                },
            )
        try:
            self.rate_limiter.check(api_key.id, api_key.rate_limit_per_minute)
        except RateLimitExceeded:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "API Key 调用过于频繁",
                        "details": {},
                    },
                    "requestId": current_request_id(),
                },
            )
        api_key.last_used_at = now
        self.session.flush()
        return ApiKeyAuthResult(api_key=api_key)

    def _get_key(self, context: AccessContext, key_id: str) -> ApiKey:
        api_key = self.repo.get_for_tenant(context.tenant_id, key_id)
        if api_key is None:
            raise not_found("API Key 不存在")
        return api_key

    def _audit(self, context: AccessContext, action: str, api_key: ApiKey, before):
        self.session.add(
            AuditLog(
                tenant_id=context.tenant_id,
                actor_id=context.user_id,
                action=action,
                resource_type="API_KEY",
                resource_id=api_key.id,
                before_snapshot=before,
                after_snapshot=self._public_dict(api_key),
                request_id=current_request_id(),
            )
        )

    @staticmethod
    def _public_dict(api_key: ApiKey) -> dict:
        return {
            "id": api_key.id,
            "name": api_key.name,
            "keyPrefix": api_key.key_prefix,
            "status": api_key.status,
            "scopes": api_key.scopes or [],
            "rateLimitPerMinute": api_key.rate_limit_per_minute,
        }

    @staticmethod
    def _unauthorized(code: str, message: str) -> HTTPException:
        return HTTPException(
            status_code=401,
            detail={
                "error": {"code": code, "message": message, "details": {}},
                "requestId": current_request_id(),
            },
        )
