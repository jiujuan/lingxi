from celery import Celery
from kombu import Queue

from server.app.core.config import settings

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
