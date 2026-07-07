from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext, require_permission
from server.app.db.session import get_db
from server.app.schemas.user import (
    AdminUserResponse,
    OkResponse,
    RoleListResponse,
    UserCreateRequest,
    UserListResponse,
    UserResetPasswordRequest,
    UserUpdateRequest,
)
from server.app.services.user_admin_service import UserAdminService

router = APIRouter(tags=["users"])


@router.get("/users", response_model=UserListResponse)
def list_users(
    keyword: str | None = Query(default=None),
    department_id: str | None = Query(default=None, alias="departmentId"),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    context: AccessContext = Depends(require_permission("USER_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return UserAdminService(db).list_users(
        context,
        keyword=keyword,
        department_id=department_id,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.get("/roles", response_model=RoleListResponse)
def list_roles(
    context: AccessContext = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return {
        "data": [
            {"id": role.id, "code": role.code, "name": role.name}
            for role in UserAdminService(db).list_roles(context)
        ]
    }


@router.post("/users", response_model=AdminUserResponse)
def create_user(
    payload: UserCreateRequest,
    context: AccessContext = Depends(require_permission("USER_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return UserAdminService(db).create_user(
        context,
        email=payload.email,
        name=payload.name,
        password=payload.password,
        department_id=payload.department_id,
        role_ids=payload.role_ids,
    )


@router.put("/users/{user_id}", response_model=AdminUserResponse)
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    context: AccessContext = Depends(require_permission("USER_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return UserAdminService(db).update_user(
        context,
        user_id,
        email=payload.email,
        name=payload.name,
        department_id=payload.department_id,
        role_ids=payload.role_ids,
    )


@router.post("/users/{user_id}/password", response_model=OkResponse)
def reset_password(
    user_id: str,
    payload: UserResetPasswordRequest,
    context: AccessContext = Depends(require_permission("USER_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    UserAdminService(db).reset_password(context, user_id, password=payload.password)
    return {"ok": True}


@router.post("/users/{user_id}/disable", response_model=AdminUserResponse)
def disable_user(
    user_id: str,
    context: AccessContext = Depends(require_permission("USER_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return UserAdminService(db).disable_user(context, user_id)


@router.post("/users/{user_id}/enable", response_model=AdminUserResponse)
def enable_user(
    user_id: str,
    context: AccessContext = Depends(require_permission("USER_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return UserAdminService(db).enable_user(context, user_id)


@router.delete("/users/{user_id}", response_model=OkResponse)
def delete_user(
    user_id: str,
    context: AccessContext = Depends(require_permission("USER_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    UserAdminService(db).delete_user(context, user_id)
    return {"ok": True}
