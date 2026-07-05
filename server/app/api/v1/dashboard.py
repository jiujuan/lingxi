from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext, require_permission
from server.app.db.session import get_db
from server.app.schemas.dashboard import (
    DashboardSummaryResponse,
    IngestionHealthResponse,
    QaHealthResponse,
)
from server.app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    days: int = Query(default=7, ge=0, le=365),
    context: AccessContext = Depends(require_permission("DASHBOARD_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return DashboardService(db).summary(context, days)


@router.get("/ingestion-health", response_model=IngestionHealthResponse)
def get_ingestion_health(
    days: int = Query(default=7, ge=0, le=365),
    context: AccessContext = Depends(require_permission("DASHBOARD_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return DashboardService(db).ingestion_health(context, days)


@router.get("/qa-health", response_model=QaHealthResponse)
def get_qa_health(
    days: int = Query(default=7, ge=0, le=365),
    context: AccessContext = Depends(require_permission("DASHBOARD_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return DashboardService(db).qa_health(context, days)


@router.get("/recent-activity")
def get_recent_activity(
    context: AccessContext = Depends(require_permission("DASHBOARD_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return DashboardService(db).recent_activity(context)

