from server.app.db.session import SessionLocal
from server.app.core.service_factory import build_embedding_service
from server.app.tasks._common import handle_failure, job_result, resolve_task_outcome
from server.app.tasks.celery_app import celery_app


@celery_app.task(
    bind=True,
    acks_late=True,
    max_retries=3,
    name="server.app.tasks.embedding_tasks.embed_qa_pairs_task",
)
def embed_qa_pairs_task(
    self,
    job_id: str,
    _legacy_chunk_indexing_enabled: bool | None = None,
) -> dict:
    """Embed Settings-selected QA targets and optional Child chunks.

    ``_legacy_chunk_indexing_enabled`` is retained solely for Celery backlog
    wire compatibility with previously queued two-argument messages.  It is
    deliberately ignored: feature flags are resolved only through Settings/DI
    by the centralized service factory, never by a Celery payload or service
    environment read.
    """
    with SessionLocal() as session:
        job = build_embedding_service(session).embed_import_job(job_id)
        outcome = resolve_task_outcome(session, job, "embed_qa_pairs_task")
        if outcome.failed:
            handle_failure(self, outcome)  # raises: retry or terminal
        return job_result(job)
