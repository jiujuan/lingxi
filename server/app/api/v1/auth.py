from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from server.app.core.errors import forbidden
from server.app.core.permissions import AccessContext, get_current_access_context
from server.app.db.session import get_db
from server.app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse
from server.app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    return AuthService(db).login(payload.email, payload.password)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> dict:
    return AuthService(db).refresh(payload.refresh_token)


@router.post("/logout")
def logout(_context: AccessContext = Depends(get_current_access_context)) -> dict:
    return {"ok": True}


@router.get("/me")
def me(context: AccessContext = Depends(get_current_access_context)) -> dict:
    return {
        "id": context.user_id,
        "tenantId": context.tenant_id,
        "departmentId": context.department_id,
        "email": context.email,
        "name": context.name,
        "roles": sorted(context.role_codes),
        "permissions": sorted(context.permissions),
    }


@router.get("/permission-check")
def permission_check(
    permission: str = Query(...),
    context: AccessContext = Depends(get_current_access_context),
) -> dict:
    if permission not in context.permissions:
        raise forbidden("权限不足")
    return {"allowed": True, "permission": permission}
