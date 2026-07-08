from server.app.core.config import settings
from server.app.db.session import SessionLocal
from server.app.integrations.storage.registry import get_storage_adapter
from server.app.services.log_archive_service import LogArchiveService
from server.app.tasks.celery_app import celery_app


@celery_app.task(
    acks_late=True,
    name="server.app.tasks.maintenance_tasks.archive_api_call_logs_task",
)
def archive_api_call_logs_task() -> dict:
    """Archive api_call_logs older than the retention window to object storage.

    Runs in the maintenance window (Celery beat); see beat_schedule in
    celery_app. Each day partition is uploaded before its rows are deleted, so
    an interrupted run loses nothing and re-running is idempotent.
    """
    storage = get_storage_adapter()
    with SessionLocal() as session:
        stats = LogArchiveService(session, storage).archive_api_call_logs(
            settings.api_call_log_retention_days
        )
    return stats.as_dict()
