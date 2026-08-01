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
def split_document_qa_task(
    self, job_id: str, *, enqueue_embedding: bool = True
) -> dict:
    with SessionLocal() as session:
        service = build_qa_split_service(session)
        job, task_run_id = service.split_import_job_for_task(job_id)
        outcome = resolve_task_outcome(
            session,
            job,
            "split_document_qa_task",
            task_run_id=task_run_id,
        )
        if outcome.failed:
            handle_failure(self, outcome)  # raises: retry or terminal
        if enqueue_embedding and job.stage == "EMBEDDING" and job.status == "RUNNING":
            try:
                enqueue_embedding_task(job.id)
            except Exception:
                if task_run_id is None:
                    raise
                job = service.mark_embedding_enqueue_failed(job.id, task_run_id)
                outcome = resolve_task_outcome(
                    session,
                    job,
                    "split_document_qa_task",
                    task_run_id=task_run_id,
                )
                handle_failure(self, outcome)
        return job_result(job)
