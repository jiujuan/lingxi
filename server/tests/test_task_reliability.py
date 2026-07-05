import types

import pytest

import server.app.db.base  # noqa: F401  (load mappers before repo/service imports)
from server.app.tasks._common import (
    TaskOutcome,
    TaskProcessingError,
    handle_failure,
    resolve_task_outcome,
    retry_countdown,
)


class _FakeTask:
    name = "fake_task"
    max_retries = 3

    def __init__(self, retries: int) -> None:
        self.request = types.SimpleNamespace(retries=retries)

    def retry(self, exc=None, countdown=None):  # mimics Celery Task.retry
        raise RuntimeError(f"RETRY:{countdown}")


def test_retry_countdown_is_exponential_and_capped():
    assert retry_countdown(0) == 5.0
    assert retry_countdown(1) == 10.0
    assert retry_countdown(2) == 20.0
    assert retry_countdown(100) == 600.0  # capped


def test_handle_failure_retries_while_retryable_and_attempts_remain():
    outcome = TaskOutcome(failed=True, retryable=True, code="X", message="boom")
    with pytest.raises(RuntimeError, match="RETRY:5.0"):
        handle_failure(_FakeTask(retries=0), outcome)


def test_handle_failure_raises_terminal_when_retries_exhausted():
    outcome = TaskOutcome(failed=True, retryable=True, code="X", message="boom")
    with pytest.raises(TaskProcessingError):
        handle_failure(_FakeTask(retries=3), outcome)


def test_handle_failure_raises_terminal_when_not_retryable():
    outcome = TaskOutcome(failed=True, retryable=False, code="BAD", message="permanent")
    with pytest.raises(TaskProcessingError) as excinfo:
        handle_failure(_FakeTask(retries=0), outcome)
    assert excinfo.value.code == "BAD"


def _seed_failed_job(session, tenant_id, task_type, retryable):
    from server.app.models.import_job import ImportJob, ImportJobStatus
    from server.app.models.logs import TaskRun

    job = ImportJob(
        tenant_id=tenant_id,
        document_id=None,
        status=ImportJobStatus.FAILED.value,
        stage="PARSING",
        error_code="PARSE_FAILED",
        error_message="boom",
    )
    session.add(job)
    session.flush()
    session.add(
        TaskRun(
            tenant_id=tenant_id,
            task_type=task_type,
            queue_name="parse",
            resource_type="IMPORT_JOB",
            resource_id=job.id,
            stage="PARSING",
            status="FAILED",
            error={"code": "PARSE_FAILED", "retryable": retryable},
        )
    )
    session.commit()
    return job


def test_resolve_task_outcome_success_for_non_failed_job():
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    from server.app.models.import_job import ImportJob, ImportJobStatus

    job = ImportJob(
        tenant_id=identity["tenant"].id,
        document_id=None,
        status=ImportJobStatus.RUNNING.value,
        stage="PARSING",
    )
    session.add(job)
    session.commit()

    outcome = resolve_task_outcome(session, job, "parse_document_task")
    assert outcome.failed is False


def test_resolve_task_outcome_reads_retryable_flag_from_task_run():
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    tenant_id = identity["tenant"].id

    retryable_job = _seed_failed_job(session, tenant_id, "parse_document_task", True)
    terminal_job = _seed_failed_job(session, tenant_id, "parse_document_task", False)

    assert resolve_task_outcome(session, retryable_job, "parse_document_task").retryable is True
    terminal = resolve_task_outcome(session, terminal_job, "parse_document_task")
    assert terminal.failed is True
    assert terminal.retryable is False
    assert terminal.code == "PARSE_FAILED"


def test_enqueue_parse_task_raises_on_broker_failure(monkeypatch):
    from server.app.services import import_service
    from server.app.tasks import parse_tasks

    def _boom(*_args, **_kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(parse_tasks.parse_document_task, "apply_async", _boom)

    with pytest.raises(ConnectionError):
        import_service.enqueue_parse_task("job-1")


def test_embedding_task_is_idempotent_for_completed_job():
    from server.tests.test_embedding_task import (
        add_default_embedding_model,
        add_qa_pairs,
        prepare_embedding_job,
    )
    from server.tests.test_qa_split_task import build_qa_session

    from sqlalchemy import func, select

    from server.app.models.logs import TaskRun
    from server.app.services.embedding_service import EmbeddingService

    session, identity = build_qa_session()
    tenant_id = identity["tenant"].id
    job_id, document_id, chunks = prepare_embedding_job(session, identity)
    add_default_embedding_model(session, tenant_id, expected_dimension=4)
    add_qa_pairs(session, tenant_id, document_id, job_id, [c.id for c in chunks])

    first = EmbeddingService(session).embed_import_job(job_id)
    assert first.status == "COMPLETED"
    runs_after_first = session.scalar(
        select(func.count()).select_from(TaskRun).where(TaskRun.resource_id == job_id)
    )

    # A duplicate delivery must not re-process or create another TaskRun.
    second = EmbeddingService(session).embed_import_job(job_id)
    runs_after_second = session.scalar(
        select(func.count()).select_from(TaskRun).where(TaskRun.resource_id == job_id)
    )

    assert second.status == "COMPLETED"
    assert runs_after_second == runs_after_first
