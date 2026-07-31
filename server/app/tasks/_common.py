"""Shared helpers for Celery task reliability.

The Celery task wrappers themselves cannot be unit-tested easily (they open a
real DB session via ``SessionLocal``), so the retry/backoff decision logic lives
here as pure, testable functions. Services still record the failure state and
persist ``TaskRun.error.retryable``; the task layer reads that back to decide
whether a retry could help.
"""

from dataclasses import dataclass
import logging

from sqlalchemy.orm import Session

from server.app.models.import_job import ImportJob, ImportJobStatus
from server.app.models.logs import TaskRun
from server.app.repositories.task_run_repo import TaskRunRepository

logger = logging.getLogger("server.app.tasks")

# Exponential backoff schedule (seconds) between retries; capped.
_RETRY_BASE_SECONDS = 5.0
_RETRY_MAX_SECONDS = 600.0


class TaskProcessingError(RuntimeError):
    """Terminal error raised by a task so Celery marks it FAILED (never silently
    succeeds). Carries the persisted error code for observability."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TaskOutcome:
    failed: bool
    retryable: bool = False
    code: str | None = None
    message: str | None = None


def retry_countdown(retries: int) -> float:
    """Exponential backoff for the given (zero-based) retry attempt number."""
    return min(_RETRY_MAX_SECONDS, _RETRY_BASE_SECONDS * (2**max(0, retries)))


def resolve_task_outcome(
    session: Session,
    job: ImportJob,
    task_type: str,
    *,
    task_run_id: str | None = None,
) -> TaskOutcome:
    """Inspect the persisted job/TaskRun state to classify a service run.

    A non-FAILED job is a success. A FAILED job's retryability comes from the
    most recent TaskRun for this job+task_type (defaulting to retryable so a
    transient failure is not accidentally treated as terminal).
    """

    if job.status != ImportJobStatus.FAILED.value:
        return TaskOutcome(failed=False)

    run = session.get(TaskRun, task_run_id) if task_run_id is not None else None
    if run is not None and (
        run.tenant_id != job.tenant_id
        or run.resource_id != job.id
        or run.task_type != task_type
    ):
        run = None
    if run is None and task_run_id is None:
        run = TaskRunRepository(session).latest_for_resource(
            job.tenant_id, job.id, task_type=task_type
        )
    error = (run.error or {}) if run is not None else {}
    return TaskOutcome(
        failed=True,
        retryable=bool(error.get("retryable", True)),
        code=error.get("code") or job.error_code,
        message=error.get("message") or job.error_message,
    )


def handle_failure(task, outcome: TaskOutcome):
    """Raise the appropriate exception for a failed outcome.

    Retries (with backoff) while the failure is retryable and attempts remain;
    otherwise raises a terminal :class:`TaskProcessingError`. Either way the task
    never returns normally on failure, so Celery records the true status.
    """

    exc = TaskProcessingError(outcome.code or "TASK_FAILED", outcome.message or "任务处理失败")
    if outcome.retryable and task.request.retries < task.max_retries:
        countdown = retry_countdown(task.request.retries)
        logger.warning(
            "task %s failed (%s), retry %d/%d in %.0fs",
            task.name,
            outcome.code,
            task.request.retries + 1,
            task.max_retries,
            countdown,
        )
        raise task.retry(exc=exc, countdown=countdown)
    logger.error(
        "task %s failed terminally (%s): %s",
        task.name,
        outcome.code,
        outcome.message,
    )
    raise exc


def job_result(job: ImportJob) -> dict:
    return {
        "jobId": job.id,
        "documentId": job.document_id,
        "status": job.status,
        "stage": job.stage,
        "errorCode": job.error_code,
    }
