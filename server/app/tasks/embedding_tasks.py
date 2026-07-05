from server.app.db.session import SessionLocal
from server.app.services.embedding_service import EmbeddingService
from server.app.tasks.celery_app import celery_app


@celery_app.task(name="server.app.tasks.embedding_tasks.embed_qa_pairs_task")
def embed_qa_pairs_task(job_id: str) -> dict:
    with SessionLocal() as session:
        job = EmbeddingService(session).embed_import_job(job_id)
        return {
            "jobId": job.id,
            "documentId": job.document_id,
            "status": job.status,
            "stage": job.stage,
            "errorCode": job.error_code,
        }
