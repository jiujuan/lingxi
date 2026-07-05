from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from server.app.models.api_key import ApiCallLog


class ApiCallLogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(
        self,
        *,
        tenant_id: str | None,
        api_key_id: str | None,
        key_prefix: str | None,
        path: str,
        method: str,
        status_code: int,
        latency_ms: int,
        error_code: str | None,
        request_id: str | None,
        request_metadata: dict | None = None,
    ) -> ApiCallLog:
        log = ApiCallLog(
            tenant_id=tenant_id,
            api_key_id=api_key_id,
            key_prefix=key_prefix,
            path=path,
            method=method,
            status_code=status_code,
            latency_ms=latency_ms,
            error_code=error_code,
            request_id=request_id,
            request_metadata=request_metadata or {},
        )
        self.session.add(log)
        self.session.flush()
        return log

    def list_for_tenant(self, tenant_id: str, limit: int = 50) -> list[ApiCallLog]:
        return list(
            self.session.scalars(
                select(ApiCallLog)
                .where(ApiCallLog.tenant_id == tenant_id)
                .order_by(ApiCallLog.created_at.desc(), ApiCallLog.id.desc())
                .limit(limit)
            ).all()
        )

    def list_page(
        self,
        tenant_id: str,
        *,
        status_code: int | None = None,
        path: str | None = None,
        key_prefix: str | None = None,
        request_id: str | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ApiCallLog], int]:
        query = select(ApiCallLog).where(ApiCallLog.tenant_id == tenant_id)
        if status_code is not None:
            query = query.where(ApiCallLog.status_code == status_code)
        if path:
            query = query.where(ApiCallLog.path.contains(path))
        if key_prefix:
            query = query.where(ApiCallLog.key_prefix == key_prefix)
        if request_id:
            query = query.where(ApiCallLog.request_id == request_id)
        if started_after:
            query = query.where(ApiCallLog.created_at >= started_after)
        if started_before:
            query = query.where(ApiCallLog.created_at <= started_before)
        return self._page(query, page, page_size)

    def _page(
        self, query: Select[tuple[ApiCallLog]], page: int, page_size: int
    ) -> tuple[list[ApiCallLog], int]:
        total = self.session.scalar(
            select(func.count()).select_from(query.subquery())
        ) or 0
        items = list(
            self.session.scalars(
                query.order_by(ApiCallLog.created_at.desc(), ApiCallLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        )
        return items, total
