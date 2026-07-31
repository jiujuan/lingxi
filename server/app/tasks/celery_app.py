import os
import sys

from celery import Celery
from celery.schedules import crontab
from kombu import Queue

# Default this process to the "worker" DB pool profile before any task module
# imports the engine, so workers size their pool independently from the API.
os.environ.setdefault("DB_ROLE", "worker")

from server.app.core.config import settings, validate_chunking_config, validate_secret_config

# Fail fast if production secrets are misconfigured before workers start.
validate_secret_config()
validate_chunking_config()

QUEUE_NAMES = settings.celery_queue_names

celery_app = Celery(
    "lingxi",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.task_queues = tuple(Queue(name) for name in QUEUE_NAMES)
celery_app.conf.task_default_queue = settings.celery_default_queue
if sys.platform == "win32":
    # billiard's prefork pool is broken on Windows (spawned pool workers hit
    # WinError 5 on shared semaphores). All tasks here are I/O-bound (HTTP to
    # model/parsing services, DB, object storage), so a thread pool is the
    # right fit for Windows dev. The CLI -P/--pool option still overrides.
    celery_app.conf.worker_pool = "threads"
    celery_app.conf.worker_concurrency = 8
celery_app.conf.imports = (
    "server.app.tasks.parse_tasks",
    "server.app.tasks.qa_tasks",
    "server.app.tasks.embedding_tasks",
    "server.app.tasks.maintenance_tasks",
)

# Maintenance window: archive old API call logs to cold storage once a day.
# Off-peak and off the :00 mark so scheduled jobs don't all pile onto the hour.
# Requires a running `celery beat` process in addition to the workers.
celery_app.conf.beat_schedule = {
    "archive-api-call-logs-daily": {
        "task": "server.app.tasks.maintenance_tasks.archive_api_call_logs_task",
        "schedule": crontab(hour=3, minute=17),
        "options": {"queue": settings.celery_default_queue},
    },
}

