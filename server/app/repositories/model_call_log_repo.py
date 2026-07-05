from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from server.app.models.model_config import ModelCallLog


class ModelCallLogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_page(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        capability: str | None = None,
        request_id: str | None = None,
        run_id: str | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ModelCallLog], int]:
        query = select(ModelCallLog).where(ModelCallLog.tenant_id == tenant_id)
        if status:
            query = query.where(ModelCallLog.status == status)
        if capability:
            query = query.where(ModelCallLog.capability == capability)
        if request_id:
            query = query.where(ModelCallLog.request_id == request_id)
        if run_id:
            query = query.where(ModelCallLog.run_id == run_id)
        if started_after:
            query = query.where(ModelCallLog.created_at >= started_after)
        if started_before:
            query = query.where(ModelCallLog.created_at <= started_before)
        return self._page(query, page, page_size)

    def _page(
        self, query: Select[tuple[ModelCallLog]], page: int, page_size: int
    ) -> tuple[list[ModelCallLog], int]:
        total = self.session.scalar(
            select(func.count()).select_from(query.subquery())
        ) or 0
        items = list(
            self.session.scalars(
                query.order_by(ModelCallLog.created_at.desc(), ModelCallLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        )
        return items, total

