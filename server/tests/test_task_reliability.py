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


def test_enqueue_parse_task_raises_on_broker_failure(monkeypatch, caplog):
    from server.app.services import import_service
    from server.app.tasks import parse_tasks

    def _boom(*_args, **_kwargs):
        raise ConnectionError("redis down: SELECT content FROM document_chunks")

    monkeypatch.setattr(parse_tasks.parse_document_task, "apply_async", _boom)
    caplog.set_level("ERROR", logger=import_service.__name__)

    with pytest.raises(ConnectionError, match="document_chunks"):
        import_service.enqueue_parse_task("safe-parse-job-id")

    assert "safe-parse-job-id" in caplog.text
    assert "SELECT content FROM document_chunks" not in caplog.text


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


def test_adaptive_chunk_backfill_task_uses_maintenance_queue_and_retries_structured_failures():
    from server.app.tasks.maintenance_tasks import backfill_adaptive_chunks_task

    assert backfill_adaptive_chunks_task.name.endswith("backfill_adaptive_chunks_task")
    assert backfill_adaptive_chunks_task.acks_late is True
    assert backfill_adaptive_chunks_task.queue == "maintenance"


def test_enqueue_qa_task_can_defer_embedding_until_qa_succeeds(monkeypatch):
    from server.app.services import import_service

    scheduled = []

    class _Task:
        @staticmethod
        def apply_async(*, args, kwargs, queue):
            scheduled.append((args, kwargs, queue))

    from server.app.tasks import qa_tasks

    monkeypatch.setattr(qa_tasks, "split_document_qa_task", _Task())

    import_service.enqueue_qa_task("job-1", enqueue_embedding=False)

    assert scheduled == [(["job-1"], {"enqueue_embedding": False}, "qa")]


def test_enqueue_qa_task_broker_failure_logs_no_exception_detail(monkeypatch, caplog):
    from server.app.services import import_service
    from server.app.tasks import qa_tasks

    sensitive = "SELECT * FROM document_chunks WHERE content='DO-NOT-LOG'"

    def _boom(*_args, **_kwargs):
        raise RuntimeError(sensitive)

    monkeypatch.setattr(qa_tasks.split_document_qa_task, "apply_async", _boom)
    caplog.set_level("ERROR", logger=import_service.__name__)

    with pytest.raises(RuntimeError, match="DO-NOT-LOG"):
        import_service.enqueue_qa_task("safe-job-id", enqueue_embedding=False)

    assert "safe-job-id" in caplog.text
    assert sensitive not in caplog.text


def test_enqueue_embedding_task_broker_failure_logs_no_exception_detail(monkeypatch, caplog):
    from server.app.services import import_service
    from server.app.tasks import embedding_tasks

    sensitive = "INSERT INTO document_chunks(content) VALUES ('DO-NOT-LOG')"

    def _boom(*_args, **_kwargs):
        raise RuntimeError(sensitive)

    monkeypatch.setattr(embedding_tasks.embed_qa_pairs_task, "apply_async", _boom)
    caplog.set_level("ERROR", logger=import_service.__name__)

    with pytest.raises(RuntimeError, match="DO-NOT-LOG"):
        import_service.enqueue_embedding_task("safe-job-id")

    assert "safe-job-id" in caplog.text
    assert sensitive not in caplog.text


def test_import_service_enqueue_failure_logs_no_exception_detail(caplog):
    from server.app.services import import_service

    sensitive = "UPDATE document_chunks SET content='DO-NOT-LOG'"

    class _Document:
        status = None
        last_error_code = None
        last_error_message = None

    class _Job:
        id = "safe-import-job-id"
        document_id = "safe-document-id"
        status = None
        error_code = None
        error_message = None

    class _Session:
        @staticmethod
        def get(_model, document_id):
            assert document_id == "safe-document-id"
            return _Document()

        @staticmethod
        def commit():
            return None

    def _boom(*_args, **_kwargs):
        raise ConnectionError(sensitive)

    caplog.set_level("ERROR", logger=import_service.__name__)
    service = import_service.ImportService(_Session(), storage=object())

    with pytest.raises(Exception):
        service._enqueue_or_mark_failed(_Job(), _boom)

    assert "safe-import-job-id" in caplog.text
    assert sensitive not in caplog.text


def test_qa_worker_enqueues_embedding_only_when_requested_after_success(monkeypatch):
    from server.app.tasks import qa_tasks
    from server.app.tasks._common import TaskOutcome

    class _Job:
        id = "job-qa-1"
        document_id = "document-qa-1"
        status = "RUNNING"
        stage = "EMBEDDING"
        error_code = None

    class _Service:
        @staticmethod
        def split_import_job_for_task(job_id):
            assert job_id == "job-qa-1"
            return _Job(), "qa-task-run-1"

    class _Session:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return False

    scheduled = []
    monkeypatch.setattr(qa_tasks, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(qa_tasks, "build_qa_split_service", lambda _session: _Service())
    monkeypatch.setattr(
        qa_tasks,
        "resolve_task_outcome",
        lambda *_args, **_kwargs: TaskOutcome(failed=False),
    )
    monkeypatch.setattr(
        qa_tasks, "enqueue_embedding_task", lambda job_id: scheduled.append(job_id)
    )

    task = qa_tasks.split_document_qa_task._get_current_object()
    task.run("job-qa-1", enqueue_embedding=False)
    assert scheduled == []

    task.run("job-qa-1", enqueue_embedding=True)
    assert scheduled == ["job-qa-1"]


def test_qa_worker_does_not_enqueue_embedding_while_qa_is_pending(monkeypatch):
    from server.app.tasks import qa_tasks
    from server.app.tasks._common import TaskOutcome

    class _Job:
        id = "job-qa-pending"
        document_id = "document-qa-pending"
        status = "RUNNING"
        stage = "QA_SPLITTING"
        error_code = None

    class _Service:
        @staticmethod
        def split_import_job_for_task(job_id):
            assert job_id == "job-qa-pending"
            return _Job(), "qa-task-run-pending"

    class _Session:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return False

    scheduled = []
    monkeypatch.setattr(qa_tasks, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(qa_tasks, "build_qa_split_service", lambda _session: _Service())
    monkeypatch.setattr(
        qa_tasks,
        "resolve_task_outcome",
        lambda *_args, **_kwargs: TaskOutcome(failed=False),
    )
    monkeypatch.setattr(
        qa_tasks, "enqueue_embedding_task", lambda job_id: scheduled.append(job_id)
    )

    task = qa_tasks.split_document_qa_task._get_current_object()
    task.run("job-qa-pending", enqueue_embedding=True)

    assert scheduled == []


def test_qa_worker_persists_retryable_failure_when_embedding_enqueue_fails(monkeypatch):
    from sqlalchemy import select

    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob, ImportJobStatus
    from server.app.models.logs import TaskRun
    from server.app.services.qa_split_service import QaSplitService
    from server.app.tasks import qa_tasks
    from server.tests.test_qa_split_task import build_qa_session, create_qa_ready_job

    class _RetrySentinel(Exception):
        pass

    session, identity = build_qa_session()
    job_id, document_id, _chunks = create_qa_ready_job(session, identity)
    job = session.get(ImportJob, job_id)
    document = session.get(Document, document_id)
    job.status = ImportJobStatus.RUNNING.value
    job.stage = "EMBEDDING"
    document.status = DocumentStatus.EMBEDDING
    task_run = TaskRun(
        tenant_id=job.tenant_id,
        task_type="split_document_qa_task",
        queue_name="qa",
        resource_type="IMPORT_JOB",
        resource_id=job.id,
        stage="QA_SPLITTING",
        status="SUCCESS",
        error=None,
    )
    session.add(task_run)
    session.commit()

    class _Session:
        def __enter__(self):
            return session

        def __exit__(self, *_args):
            return False

    class _Service:
        @staticmethod
        def split_import_job_for_task(received_job_id):
            assert received_job_id == job_id
            return session.get(ImportJob, job_id), task_run.id

        @staticmethod
        def mark_embedding_enqueue_failed(received_job_id, task_run_id):
            return QaSplitService(session).mark_embedding_enqueue_failed(
                received_job_id,
                task_run_id,
            )

    monkeypatch.setattr(qa_tasks, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(qa_tasks, "build_qa_split_service", lambda _session: _Service())
    monkeypatch.setattr(
        qa_tasks,
        "enqueue_embedding_task",
        lambda _job_id: (_ for _ in ()).throw(ConnectionError("broker unavailable")),
    )

    task = qa_tasks.split_document_qa_task._get_current_object()

    def _retry(*, exc, countdown):
        assert exc.code == "EMBEDDING_ENQUEUE_FAILED"
        assert countdown > 0
        raise _RetrySentinel()

    monkeypatch.setattr(task, "retry", _retry)
    task.push_request(retries=0)
    try:
        with pytest.raises(_RetrySentinel):
            task.run(job_id, enqueue_embedding=True)
    finally:
        task.pop_request()

    session.expire_all()
    persisted_job = session.get(ImportJob, job_id)
    persisted_document = session.get(Document, document_id)
    failed_run = session.scalar(
        select(TaskRun)
        .where(
            TaskRun.resource_id == job_id,
            TaskRun.task_type == "split_document_qa_task",
        )
        .order_by(TaskRun.created_at.desc(), TaskRun.id.desc())
    )
    assert persisted_job.status == ImportJobStatus.FAILED.value
    assert persisted_job.stage == "EMBEDDING"
    assert persisted_job.error_code == "EMBEDDING_ENQUEUE_FAILED"
    assert persisted_document.status == DocumentStatus.FAILED
    assert failed_run is not None
    assert failed_run.status == "FAILED"
    assert failed_run.error["code"] == "EMBEDDING_ENQUEUE_FAILED"
    assert failed_run.error["retryable"] is True


def test_qa_worker_marks_current_task_run_when_timestamps_collide(monkeypatch):
    from datetime import UTC, datetime
    import json

    from sqlalchemy import select

    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob, ImportJobStatus
    from server.app.models.logs import TaskRun
    from server.app.services.qa_split_service import QaSplitService
    from server.app.tasks import qa_tasks
    from server.tests.test_qa_split_task import (
        _strict_qa_payload,
        add_default_qa_model,
        build_qa_session,
        create_qa_ready_job,
    )

    class _RetrySentinel(Exception):
        pass

    session, identity = build_qa_session()
    job_id, document_id, _chunks = create_qa_ready_job(session, identity)
    job = session.get(ImportJob, job_id)
    document = session.get(Document, document_id)
    collision_at = datetime(2026, 8, 1, tzinfo=UTC)
    older_run = TaskRun(
        id="f0000000-0000-0000-0000-000000000000",
        tenant_id=job.tenant_id,
        task_type="split_document_qa_task",
        queue_name="qa",
        resource_type="IMPORT_JOB",
        resource_id=job.id,
        stage="QA_SPLITTING",
        status="SUCCESS",
        error={
            "code": "OLD_TERMINAL",
            "message": "old task run",
            "retryable": False,
        },
        created_at=collision_at,
    )
    session.add(older_run)
    session.commit()
    add_default_qa_model(session, identity["tenant"].id, {"items": []})

    class _Adapter:
        @staticmethod
        def generate_qa_pairs(_prompt):
            return json.dumps(
                _strict_qa_payload(
                    items=[
                        {
                            "question": "退款需要谁审批？",
                            "answer": "退款需要主管审批。",
                            "quote": "退款需要主管审批。",
                            "pageNo": 1,
                            "chunkIndex": 0,
                        },
                        {
                            "question": "已开票订单退款前要做什么？",
                            "answer": "先红冲发票。",
                            "quote": "已开票订单需先红冲发票。",
                            "pageNo": 2,
                            "chunkIndex": 1,
                        },
                    ],
                    covered=[0, 1],
                    skipped=[],
                )
            )

    qa_service = QaSplitService(
        session,
        provider_factory=lambda *_args, **_kwargs: _Adapter(),
    )

    class _Session:
        def __enter__(self):
            return session

        def __exit__(self, *_args):
            return False

    class _Service:
        @staticmethod
        def split_import_job_for_task(received_job_id):
            assert received_job_id == job_id
            split_job, current_run_id = qa_service.split_import_job_for_task(job_id)
            current_run = session.get(TaskRun, current_run_id)
            older_run.created_at = collision_at
            current_run.created_at = collision_at
            session.commit()
            return split_job, current_run_id

        @staticmethod
        def mark_embedding_enqueue_failed(received_job_id, task_run_id):
            return qa_service.mark_embedding_enqueue_failed(
                received_job_id,
                task_run_id,
            )

    monkeypatch.setattr(qa_tasks, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(qa_tasks, "build_qa_split_service", lambda _session: _Service())
    monkeypatch.setattr(
        qa_tasks,
        "enqueue_embedding_task",
        lambda _job_id: (_ for _ in ()).throw(ConnectionError("broker unavailable")),
    )

    task = qa_tasks.split_document_qa_task._get_current_object()
    monkeypatch.setattr(
        task,
        "retry",
        lambda **_kwargs: (_ for _ in ()).throw(_RetrySentinel()),
    )
    task.push_request(retries=0)
    try:
        with pytest.raises(_RetrySentinel):
            task.run(job_id, enqueue_embedding=True)
    finally:
        task.pop_request()

    session.expire_all()
    persisted_older = session.get(TaskRun, older_run.id)
    persisted_current = session.scalar(
        select(TaskRun)
        .where(
            TaskRun.resource_id == job_id,
            TaskRun.task_type == "split_document_qa_task",
            TaskRun.id != older_run.id,
        )
    )
    assert persisted_older.status == "SUCCESS"
    assert persisted_older.error["code"] == "OLD_TERMINAL"
    assert persisted_current is not None
    assert persisted_current.status == "FAILED"
    assert persisted_current.error["code"] == "EMBEDDING_ENQUEUE_FAILED"
    assert persisted_current.error["retryable"] is True


def test_backfill_celery_wrapper_uses_request_id_and_retries_structured_failure(monkeypatch):
    from server.app.services.chunk_backfill_service import BackfillError
    from server.app.tasks import maintenance_tasks

    class _RetrySentinel(Exception):
        pass

    class _Session:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return False

    captured = {}

    class _Service:
        @staticmethod
        def backfill(options, **kwargs):
            captured["options"] = options
            captured["kwargs"] = kwargs
            raise BackfillError("BACKFILL_TRANSIENT", "safe", retryable=True)

    monkeypatch.setattr(maintenance_tasks, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(maintenance_tasks, "_backfill_service", lambda _session: _Service())

    task = maintenance_tasks.backfill_adaptive_chunks_task._get_current_object()

    def _retry(*, exc, countdown):
        assert exc.code == "BACKFILL_TRANSIENT"
        assert countdown > 0
        raise _RetrySentinel()

    monkeypatch.setattr(task, "retry", _retry)
    task.push_request(id="celery-backfill-execution", retries=0)
    try:
        with pytest.raises(_RetrySentinel):
            task.run(dry_run=True)
    finally:
        task.pop_request()

    assert captured["options"].execution_id == "celery-backfill-execution"
    assert captured["options"].audit_source == "celery"
    assert captured["kwargs"] == {
        "task_type": "backfill_adaptive_chunks_task",
        "queue_name": "maintenance",
    }
