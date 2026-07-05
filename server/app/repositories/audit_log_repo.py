from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from server.app.models.logs import AuditLog


class AuditLogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_page(
        self,
        tenant_id: str,
        *,
        actor_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        request_id: str | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AuditLog], int]:
        query = select(AuditLog).where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.deleted_at.is_(None),
        )
        if actor_id:
            query = query.where(AuditLog.actor_id == actor_id)
        if action:
            query = query.where(AuditLog.action == action)
        if resource_type:
            query = query.where(AuditLog.resource_type == resource_type)
        if resource_id:
            query = query.where(AuditLog.resource_id == resource_id)
        if request_id:
            query = query.where(AuditLog.request_id == request_id)
        if started_after:
            query = query.where(AuditLog.created_at >= started_after)
        if started_before:
            query = query.where(AuditLog.created_at <= started_before)
        return self._page(query, page, page_size)

    def _page(
        self, query: Select[tuple[AuditLog]], page: int, page_size: int
    ) -> tuple[list[AuditLog], int]:
        total = self.session.scalar(
            select(func.count()).select_from(query.subquery())
        ) or 0
        items = list(
            self.session.scalars(
                query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        )
        return items, total

