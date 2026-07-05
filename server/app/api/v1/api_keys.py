from time import perf_counter

from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from server.app.core.ids import current_request_id
from server.app.core.permissions import AccessContext, require_permission
from server.app.db.session import get_db
from server.app.repositories.api_call_log_repo import ApiCallLogRepository
from server.app.schemas.api_key import (
    ApiCallLogListResponse,
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyListResponse,
    ApiKeyResponse,
)
from server.app.services.api_key_service import ApiKeyService

router = APIRouter(tags=["api-keys"])
api_key_scheme = HTTPBearer(auto_error=False)


@router.get("/api-keys", response_model=ApiKeyListResponse)
def list_api_keys(
    context: AccessContext = Depends(require_permission("API_KEY_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return {"data": [_api_key_to_dict(item) for item in ApiKeyService(db).list_keys(context)]}


@router.post("/api-keys", response_model=ApiKeyCreateResponse)
def create_api_key(
    payload: ApiKeyCreateRequest,
    context: AccessContext = Depends(require_permission("API_KEY_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    api_key, plaintext = ApiKeyService(db).create_key(
        context,
        name=payload.name,
        scopes=payload.scopes,
        allowed_department_ids=payload.allowed_department_ids,
        allowed_role_ids=payload.allowed_role_ids,
        rate_limit_per_minute=payload.rate_limit_per_minute,
        expires_at=payload.expires_at,
    )
    return {
        **_api_key_to_dict(api_key),
        "key": plaintext,
        "warning": "密钥明文只展示一次，请妥善保存。",
    }


@router.post("/api-keys/{key_id}/disable", response_model=ApiKeyResponse)
def disable_api_key(
    key_id: str,
    context: AccessContext = Depends(require_permission("API_KEY_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return _api_key_to_dict(ApiKeyService(db).disable_key(context, key_id))


@router.post("/api-keys/{key_id}/rotations", response_model=ApiKeyCreateResponse)
def rotate_api_key(
    key_id: str,
    context: AccessContext = Depends(require_permission("API_KEY_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    api_key, plaintext = ApiKeyService(db).rotate_key(context, key_id)
    return {
        **_api_key_to_dict(api_key),
        "key": plaintext,
        "warning": "密钥明文只展示一次，请妥善保存。",
    }


@router.get("/api-call-logs", response_model=ApiCallLogListResponse)
def list_api_call_logs(
    context: AccessContext = Depends(require_permission("LOG_READ")),
    db: Session = Depends(get_db),
) -> dict:
    logs = ApiCallLogRepository(db).list_for_tenant(context.tenant_id)
    return {
        "data": [
            {
                "id": item.id,
                "key_prefix": item.key_prefix,
                "path": item.path,
                "method": item.method,
                "status_code": item.status_code,
                "latency_ms": item.latency_ms,
                "error_code": item.error_code,
                "request_id": item.request_id,
                "created_at": item.created_at.isoformat() if item.created_at else "",
            }
            for item in logs
        ]
    }


@router.get("/api-key-auth/probe")
def api_key_auth_probe(
    request: Request,
    scope: str = Query(default="chat:read"),
    credentials: HTTPAuthorizationCredentials | None = Depends(api_key_scheme),
    db: Session = Depends(get_db),
) -> dict:
    started = perf_counter()
    service = ApiKeyService(db)
    auth_header_present = credentials is not None
    key_prefix = None
    api_key = None
    status_code = 200
    error_code = None
    try:
        if credentials is None:
            raise service._unauthorized("INVALID_API_KEY", "API Key 缺失")
        key_prefix = credentials.credentials[:16]
        result = service.authenticate(credentials.credentials, required_scope=scope)
        api_key = result.api_key
        return {"ok": True, "keyPrefix": api_key.key_prefix, "scopes": api_key.scopes}
    except Exception as exc:
        status_code = getattr(exc, "status_code", 500)
        detail = getattr(exc, "detail", {})
        if isinstance(detail, dict):
            error_code = (detail.get("error") or {}).get("code")
        raise
    finally:
        ApiCallLogRepository(db).add(
            tenant_id=api_key.tenant_id if api_key is not None else None,
            api_key_id=api_key.id if api_key is not None else None,
            key_prefix=api_key.key_prefix if api_key is not None else key_prefix,
            path=str(request.url.path),
            method=request.method,
            status_code=status_code,
            latency_ms=max(1, int((perf_counter() - started) * 1000)),
            error_code=error_code,
            request_id=current_request_id(),
            request_metadata={"authHeaderPresent": auth_header_present},
        )
        db.commit()


def _api_key_to_dict(item) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "key_prefix": item.key_prefix,
        "status": item.status,
        "scopes": item.scopes or [],
        "allowed_department_ids": item.allowed_department_ids or [],
        "allowed_role_ids": item.allowed_role_ids or [],
        "rate_limit_per_minute": item.rate_limit_per_minute,
        "last_used_at": item.last_used_at.isoformat() if item.last_used_at else None,
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else "",
    }
