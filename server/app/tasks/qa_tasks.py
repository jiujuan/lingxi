from server.app.db.session import SessionLocal
from server.app.services.import_service import enqueue_embedding_task
from server.app.core.service_factory import build_qa_split_service
from server.app.tasks._common import handle_failure, job_result, resolve_task_outcome
from server.app.tasks.celery_app import celery_app


@celery_app.task(
    bind=True,
    acks_late=True,
    max_retries=3,
    name="server.app.tasks.qa_tasks.split_document_qa_task",
)
def split_document_qa_task(self, job_id: str) -> dict:
    with SessionLocal() as session:
        job = build_qa_split_service(session).split_import_job(job_id)
        outcome = resolve_task_outcome(session, job, "split_document_qa_task")
        if outcome.failed:
            handle_failure(self, outcome)  # raises: retry or terminal
        if job.stage == "EMBEDDING" and job.status == "RUNNING":
            enqueue_embedding_task(job.id)  # raises on broker failure -> task retry
        return job_result(job)
