from server.app.db.session import SessionLocal
from server.app.services.embedding_service import EmbeddingService
from server.app.tasks._common import handle_failure, job_result, resolve_task_outcome
from server.app.tasks.celery_app import celery_app


@celery_app.task(
    bind=True,
    acks_late=True,
    max_retries=3,
    name="server.app.tasks.embedding_tasks.embed_qa_pairs_task",
)
def embed_qa_pairs_task(self, job_id: str) -> dict:
    with SessionLocal() as session:
        job = EmbeddingService(session).embed_import_job(job_id)
        outcome = resolve_task_outcome(session, job, "embed_qa_pairs_task")
        if outcome.failed:
            handle_failure(self, outcome)  # raises: retry or terminal
        return job_result(job)
