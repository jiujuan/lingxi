from server.app.db.session import SessionLocal
from server.app.services.qa_split_service import QaSplitService, enqueue_embedding_task
from server.app.tasks.celery_app import celery_app


@celery_app.task(name="server.app.tasks.qa_tasks.split_document_qa_task")
def split_document_qa_task(job_id: str) -> dict:
    with SessionLocal() as session:
        job = QaSplitService(session).split_import_job(job_id)
        if job.stage == "EMBEDDING" and job.status == "RUNNING":
            enqueue_embedding_task(job.id)
        return {
            "jobId": job.id,
            "documentId": job.document_id,
            "status": job.status,
            "stage": job.stage,
            "errorCode": job.error_code,
        }
