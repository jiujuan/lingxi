from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from server.app.core.errors import not_found
from server.app.core.permissions import AccessContext, require_permission
from server.app.db.session import get_db
from server.app.schemas.logs import (
    ApiCallLogListResponse,
    AuditLogListResponse,
    ModelCallLogListResponse,
    TaskRunLogListResponse,
    TaskRunLogResponse,
)
from server.app.services.log_query_service import LogQueryService

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/task-runs", response_model=TaskRunLogListResponse)
def list_task_runs(
    status: str | None = Query(default=None),
    task_type: str | None = Query(default=None, alias="taskType"),
    document_id: str | None = Query(default=None, alias="documentId"),
    resource_id: str | None = Query(default=None, alias="resourceId"),
    request_id: str | None = Query(default=None, alias="requestId"),
    task_run_id: str | None = Query(default=None, alias="taskRunId"),
    started_after: datetime | None = Query(default=None, alias="startedAfter"),
    started_before: datetime | None = Query(default=None, alias="startedBefore"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    context: AccessContext = Depends(require_permission("LOG_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return LogQueryService(db).list_task_runs(
        context,
        status=status,
        task_type=task_type,
        document_id=document_id,
        resource_id=resource_id,
        request_id=request_id,
        task_run_id=task_run_id,
        started_after=started_after,
        started_before=started_before,
        page=page,
        page_size=page_size,
    )


@router.get("/task-runs/{task_run_id}", response_model=TaskRunLogResponse)
def get_task_run(
    task_run_id: str,
    context: AccessContext = Depends(require_permission("LOG_READ")),
    db: Session = Depends(get_db),
) -> dict:
    item = LogQueryService(db).get_task_run(context, task_run_id)
    if item is None:
        raise not_found("任务日志不存在")
    return item


@router.get("/model-calls", response_model=ModelCallLogListResponse)
def list_model_calls(
    status: str | None = Query(default=None),
    capability: str | None = Query(default=None),
    request_id: str | None = Query(default=None, alias="requestId"),
    run_id: str | None = Query(default=None, alias="runId"),
    batch_id: str | None = Query(default=None, alias="batchId"),
    timeout_phase: str | None = Query(default=None, alias="timeoutPhase"),
    provider_id: str | None = Query(default=None, alias="providerId"),
    model_config_id: str | None = Query(default=None, alias="modelConfigId"),
    started_after: datetime | None = Query(default=None, alias="startedAfter"),
    started_before: datetime | None = Query(default=None, alias="startedBefore"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    context: AccessContext = Depends(require_permission("LOG_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return LogQueryService(db).list_model_calls(
        context,
        status=status,
        capability=capability,
        request_id=request_id,
        run_id=run_id,
        batch_id=batch_id,
        timeout_phase=timeout_phase,
        provider_id=provider_id,
        model_config_id=model_config_id,
        started_after=started_after,
        started_before=started_before,
        page=page,
        page_size=page_size,
    )


@router.get("/api-calls", response_model=ApiCallLogListResponse)
def list_api_calls(
    status_code: int | None = Query(default=None, alias="statusCode"),
    path: str | None = Query(default=None),
    key_prefix: str | None = Query(default=None, alias="keyPrefix"),
    request_id: str | None = Query(default=None, alias="requestId"),
    started_after: datetime | None = Query(default=None, alias="startedAfter"),
    started_before: datetime | None = Query(default=None, alias="startedBefore"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    context: AccessContext = Depends(require_permission("LOG_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return LogQueryService(db).list_api_calls(
        context,
        status_code=status_code,
        path=path,
        key_prefix=key_prefix,
        request_id=request_id,
        started_after=started_after,
        started_before=started_before,
        page=page,
        page_size=page_size,
    )


@router.get("/audit", response_model=AuditLogListResponse)
def list_audit_logs(
    actor_id: str | None = Query(default=None, alias="actorId"),
    action: str | None = Query(default=None),
    resource_type: str | None = Query(default=None, alias="resourceType"),
    resource_id: str | None = Query(default=None, alias="resourceId"),
    request_id: str | None = Query(default=None, alias="requestId"),
    started_after: datetime | None = Query(default=None, alias="startedAfter"),
    started_before: datetime | None = Query(default=None, alias="startedBefore"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    context: AccessContext = Depends(require_permission("AUDIT_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return LogQueryService(db).list_audit_logs(
        context,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        started_after=started_after,
        started_before=started_before,
        page=page,
        page_size=page_size,
    )
