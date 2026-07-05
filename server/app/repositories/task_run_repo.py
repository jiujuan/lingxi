from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from server.app.models.logs import TaskRun


class TaskRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_for_tenant(self, tenant_id: str, task_run_id: str) -> TaskRun | None:
        return self.session.scalar(
            select(TaskRun).where(
                TaskRun.tenant_id == tenant_id,
                TaskRun.id == task_run_id,
                TaskRun.deleted_at.is_(None),
            )
        )

    def latest_for_resource(
        self, tenant_id: str, resource_id: str, task_type: str | None = None
    ) -> TaskRun | None:
        query = select(TaskRun).where(
            TaskRun.tenant_id == tenant_id,
            TaskRun.resource_id == resource_id,
            TaskRun.deleted_at.is_(None),
        )
        if task_type:
            query = query.where(TaskRun.task_type == task_type)
        return self.session.scalar(
            query.order_by(TaskRun.created_at.desc(), TaskRun.id.desc())
        )

    def list_page(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        task_type: str | None = None,
        document_id: str | None = None,
        request_id: str | None = None,
        task_run_id: str | None = None,
        resource_id: str | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[TaskRun], int]:
        query = select(TaskRun).where(
            TaskRun.tenant_id == tenant_id,
            TaskRun.deleted_at.is_(None),
        )
        if status:
            query = query.where(TaskRun.status == status)
        if task_type:
            query = query.where(TaskRun.task_type == task_type)
        if document_id:
            query = query.where(TaskRun.resource_id == document_id)
        if resource_id:
            query = query.where(TaskRun.resource_id == resource_id)
        if request_id:
            query = query.where(TaskRun.request_id == request_id)
        if task_run_id:
            query = query.where(TaskRun.id == task_run_id)
        if started_after:
            query = query.where(TaskRun.created_at >= started_after)
        if started_before:
            query = query.where(TaskRun.created_at <= started_before)
        return self._page(query, page, page_size)

    def _page(
        self, query: Select[tuple[TaskRun]], page: int, page_size: int
    ) -> tuple[list[TaskRun], int]:
        total = self.session.scalar(
            select(func.count()).select_from(query.subquery())
        ) or 0
        items = list(
            self.session.scalars(
                query.order_by(TaskRun.created_at.desc(), TaskRun.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        )
        return items, total

