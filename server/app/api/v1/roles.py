from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext, require_permission
from server.app.db.session import get_db
from server.app.schemas.common import OkResponse
from server.app.schemas.role import (
    PermissionCatalogResponse,
    RoleDetailResponse,
    RoleListResponse,
    RoleOptionsResponse,
    RoleUpsertRequest,
)
from server.app.services.role_service import RoleService

router = APIRouter(tags=["roles"])


@router.get("/roles", response_model=RoleListResponse)
def list_roles(
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    context: AccessContext = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return RoleService(db).list_roles(
        context, keyword=keyword, page=page, page_size=page_size
    )


@router.get("/roles/options", response_model=RoleOptionsResponse)
def list_role_options(
    context: AccessContext = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return {"data": RoleService(db).list_role_options(context)}


@router.get("/roles/available-permissions", response_model=PermissionCatalogResponse)
def list_available_permissions(
    context: AccessContext = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return {"data": RoleService(db).list_available_permissions(context)}


@router.get("/roles/{role_id}", response_model=RoleDetailResponse)
def get_role(
    role_id: str,
    context: AccessContext = Depends(require_permission("ROLE_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return RoleService(db).get_role(context, role_id)


@router.post("/roles", response_model=RoleDetailResponse)
def create_role(
    payload: RoleUpsertRequest,
    context: AccessContext = Depends(require_permission("ROLE_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return RoleService(db).create_role(
        context,
        name=payload.name,
        code=payload.code,
        permission_ids=payload.permission_ids,
    )


@router.put("/roles/{role_id}", response_model=RoleDetailResponse)
def update_role(
    role_id: str,
    payload: RoleUpsertRequest,
    context: AccessContext = Depends(require_permission("ROLE_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return RoleService(db).update_role(
        context,
        role_id,
        name=payload.name,
        code=payload.code,
        permission_ids=payload.permission_ids,
    )


@router.delete("/roles/{role_id}", response_model=OkResponse)
def delete_role(
    role_id: str,
    context: AccessContext = Depends(require_permission("ROLE_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    RoleService(db).delete_role(context, role_id)
    return {"ok": True}