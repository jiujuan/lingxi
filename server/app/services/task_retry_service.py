from sqlalchemy.orm import Session

from server.app.core.errors import conflict, not_found
from server.app.core.permissions import AccessContext
from server.app.repositories.task_run_repo import TaskRunRepository
from server.app.services.import_service import ImportService


class TaskRetryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def retry_task_run(self, context: AccessContext, task_run_id: str) -> dict:
        task_run = TaskRunRepository(self.session).get_for_tenant(
            context.tenant_id, task_run_id
        )
        if task_run is None:
            raise not_found("任务日志不存在")
        if task_run.status != "FAILED":
            raise conflict("STATE_CONFLICT", "只有失败任务可以重试")
        if task_run.resource_type != "IMPORT_JOB":
            raise conflict("UNSUPPORTED_TASK_RETRY", "当前任务类型暂不支持重试")

        job, _job_file = ImportService(self.session).retry_job(
            context, task_run.resource_id
        )
        return {
            "id": task_run.id,
            "resource_id": task_run.resource_id,
            "status": job.status,
            "stage": job.stage,
            "retry_count": job.retry_count,
        }

