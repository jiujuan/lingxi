from server.app.db.session import SessionLocal
from server.app.services.document_parse_service import DocumentParseService
from server.app.tasks.celery_app import celery_app


@celery_app.task(name="server.app.tasks.parse_tasks.parse_document_task")
def parse_document_task(job_id: str) -> dict:
    with SessionLocal() as session:
        job = DocumentParseService(session).parse_import_job(job_id)
        if job.stage == "QA_SPLITTING" and job.status == "RUNNING":
            from server.app.tasks.qa_tasks import split_document_qa_task

            split_document_qa_task.apply_async(args=[job.id], queue="qa")
        return {
            "jobId": job.id,
            "documentId": job.document_id,
            "status": job.status,
            "stage": job.stage,
            "errorCode": job.error_code,
        }
