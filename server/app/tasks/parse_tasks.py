from server.app.db.session import SessionLocal
from server.app.core.service_factory import build_document_parse_service
from server.app.services.import_service import enqueue_qa_task
from server.app.tasks._common import handle_failure, job_result, resolve_task_outcome
from server.app.tasks.celery_app import celery_app


@celery_app.task(
    bind=True,
    acks_late=True,
    max_retries=3,
    name="server.app.tasks.parse_tasks.parse_document_task",
)
def parse_document_task(self, job_id: str) -> dict:
    with SessionLocal() as session:
        job = build_document_parse_service(session).parse_import_job(job_id)
        outcome = resolve_task_outcome(session, job, "parse_document_task")
        if outcome.failed:
            handle_failure(self, outcome)  # raises: retry or terminal
        if job.stage == "QA_SPLITTING" and job.status == "RUNNING":
            enqueue_qa_task(job.id)  # raises on broker failure -> task retry
        return job_result(job)
