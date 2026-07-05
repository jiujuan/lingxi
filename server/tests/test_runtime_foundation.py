from fastapi.testclient import TestClient


def test_health_check_returns_request_id():
    from server.app.main import app

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["requestId"]
    assert response.headers["x-request-id"] == response.json()["requestId"]


def test_celery_queues_are_registered():
    from server.app.tasks.celery_app import QUEUE_NAMES, celery_app

    assert QUEUE_NAMES == ("parse", "qa", "embedding", "maintenance")
    assert {queue.name for queue in celery_app.conf.task_queues} == set(QUEUE_NAMES)

