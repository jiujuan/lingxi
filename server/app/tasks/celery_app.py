import os

from celery import Celery
from kombu import Queue

# Default this process to the "worker" DB pool profile before any task module
# imports the engine, so workers size their pool independently from the API.
os.environ.setdefault("DB_ROLE", "worker")

from server.app.core.config import settings, validate_secret_config

# Fail fast if production secrets are misconfigured before workers start.
validate_secret_config()

QUEUE_NAMES = settings.celery_queue_names

celery_app = Celery(
    "lingxi",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.task_queues = tuple(Queue(name) for name in QUEUE_NAMES)
celery_app.conf.task_default_queue = settings.celery_default_queue
celery_app.conf.imports = (
    "server.app.tasks.parse_tasks",
    "server.app.tasks.qa_tasks",
    "server.app.tasks.embedding_tasks",
)
