from sqlalchemy import select

from server.app.core.service_factory import ServiceDependencies
from server.app.db.session import SessionLocal
from server.app.models.document import Document, DocumentStatus
from server.app.models.import_job import ImportJob, ImportJobStatus
from server.app.services.chunk_backfill_service import (
    BackfillError,
    BackfillOptions,
    ChunkBackfillService,
)
from server.app.services.chunking import ChunkingService
from server.app.services.import_service import enqueue_qa_task
from server.app.tasks._common import TaskOutcome, handle_failure
from server.app.tasks.celery_app import celery_app


def schedule_qa_rebuild(
    session, document: Document, *, enqueue_embedding: bool
) -> None:
    """Re-arm the latest legal import job and dispatch the existing QA task.

    The QA worker owns actual model invocation. When embedding is requested,
    the QA task queues embedding only after QA has committed a generation-bound
    QA result; backfill never pre-queues embedding against superseded chunks.
    """
    job = session.scalar(
        select(ImportJob)
        .where(
            ImportJob.tenant_id == document.tenant_id,
            ImportJob.document_id == document.id,
            ImportJob.deleted_at.is_(None),
        )
        .order_by(ImportJob.created_at.desc(), ImportJob.id.desc())
    )
    if job is None:
        raise BackfillError(
            "CHUNK_BACKFILL_IMPORT_JOB_MISSING",
            "document has no import job for QA rebuild",
            retryable=False,
        )

    job.status = ImportJobStatus.RUNNING.value
    job.stage = "QA_SPLITTING"
    job.progress = 45
    job.error_code = None
    job.error_message = None
    document.status = DocumentStatus.QA_SPLITTING
    document.last_error_code = None
    document.last_error_message = None
    session.commit()

    try:
        enqueue_qa_task(job.id, enqueue_embedding=enqueue_embedding)
    except Exception as exc:
        session.rollback()
        persisted_job = session.get(ImportJob, job.id)
        persisted_document = session.get(Document, document.id)
        if persisted_job is not None:
            persisted_job.status = ImportJobStatus.FAILED.value
            persisted_job.stage = "QA_SPLITTING"
            persisted_job.error_code = "CHUNK_BACKFILL_QA_SCHEDULE_FAILED"
            persisted_job.error_message = "QA 重建任务入队失败"
        if persisted_document is not None:
            persisted_document.status = DocumentStatus.FAILED
            persisted_document.last_error_code = "CHUNK_BACKFILL_QA_SCHEDULE_FAILED"
            persisted_document.last_error_message = "QA 重建任务入队失败"
        session.commit()
        raise BackfillError(
            "CHUNK_BACKFILL_QA_SCHEDULE_FAILED",
            "QA rebuild scheduling failed",
            retryable=True,
        ) from exc


def _backfill_service(session) -> ChunkBackfillService:
    dependencies = ServiceDependencies.from_settings()
    counter = dependencies.build_token_counter()
    return ChunkBackfillService(
        session,
        chunking_service=ChunkingService(counter),
        chunking_policy=dependencies.build_chunk_policy(counter),
        qa_rebuilder=lambda document, enqueue_embedding: schedule_qa_rebuild(
            session, document, enqueue_embedding=enqueue_embedding
        ),
    )


@celery_app.task(
    bind=True,
    acks_late=True,
    max_retries=3,
    queue="maintenance",
    name="server.app.tasks.maintenance_tasks.backfill_adaptive_chunks_task",
)
def backfill_adaptive_chunks_task(
    self,
    *,
    tenant_id: str | None = None,
    document_id: str | None = None,
    from_chunker_version: str | None = None,
    to_chunker_version: str | None = None,
    batch_size: int = 100,
    resume_after: str | None = None,
    dry_run: bool = False,
    rebuild_qa: bool = False,
    rebuild_embedding: bool = False,
) -> dict:
    """Run one resumable maintenance batch on the dedicated queue.

    The service records a DOCUMENT TaskRun for each non-dry-run target.  A
    failed collection leaves the old ACTIVE version intact and is surfaced as a
    normal structured Celery retry/final failure rather than a false success.
    """
    options = BackfillOptions(
        tenant_id=tenant_id,
        document_id=document_id,
        from_chunker_version=from_chunker_version,
        to_chunker_version=to_chunker_version,
        batch_size=batch_size,
        resume_after=resume_after,
        dry_run=dry_run,
        rebuild_qa=rebuild_qa,
        rebuild_embedding=rebuild_embedding,
        execution_id=getattr(self.request, "id", None),
        audit_source="celery",
    )
    with SessionLocal() as session:
        try:
            result = _backfill_service(session).backfill(
                options,
                task_type="backfill_adaptive_chunks_task",
                queue_name="maintenance",
            )
        except BackfillError as exc:
            handle_failure(
                self,
                TaskOutcome(
                    failed=True,
                    retryable=exc.retryable,
                    code=exc.code,
                    message="adaptive chunk backfill failed",
                ),
            )
            raise AssertionError("handle_failure must raise")  # pragma: no cover
        return result.as_dict()


@celery_app.task(
    acks_late=True,
    queue="maintenance",
    name="server.app.tasks.maintenance_tasks.archive_api_call_logs_task",
)
def archive_api_call_logs_task() -> dict:
    """Archive api_call_logs older than the retention window to object storage.

    Runs in the maintenance window (Celery beat); see beat_schedule in
    celery_app. Each day partition is uploaded before its rows are deleted, so
    an interrupted run loses nothing and re-running is idempotent.
    """
    from server.app.core.config import settings
    from server.app.integrations.storage.registry import get_storage_adapter
    from server.app.services.log_archive_service import LogArchiveService

    storage = get_storage_adapter()
    with SessionLocal() as session:
        stats = LogArchiveService(session, storage).archive_api_call_logs(
            settings.api_call_log_retention_days
        )
    return stats.as_dict()
