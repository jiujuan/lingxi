from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext, require_permission
from server.app.db.session import get_db
from server.app.schemas.department import (
    DepartmentCreateRequest,
    DepartmentListResponse,
    DepartmentResponse,
    DepartmentUpdateRequest,
)
from server.app.schemas.common import OkResponse
from server.app.services.department_service import DepartmentService

router = APIRouter(tags=["departments"])


@router.get("/departments", response_model=DepartmentListResponse)
def list_departments(
    context: AccessContext = Depends(require_permission("USER_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return {"data": DepartmentService(db).list_departments(context)}


@router.post("/departments", response_model=DepartmentResponse)
def create_department(
    payload: DepartmentCreateRequest,
    context: AccessContext = Depends(require_permission("USER_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return DepartmentService(db).create_department(
        context, name=payload.name, code=payload.code, parent_id=payload.parent_id
    )


@router.put("/departments/{department_id}", response_model=DepartmentResponse)
def update_department(
    department_id: str,
    payload: DepartmentUpdateRequest,
    context: AccessContext = Depends(require_permission("USER_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return DepartmentService(db).update_department(
        context,
        department_id,
        name=payload.name,
        code=payload.code,
        parent_id=payload.parent_id,
    )


@router.delete("/departments/{department_id}", response_model=OkResponse)
def delete_department(
    department_id: str,
    context: AccessContext = Depends(require_permission("USER_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    DepartmentService(db).delete_department(context, department_id)
    return {"ok": True}
