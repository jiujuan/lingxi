def test_health_check_returns_request_id():
    from server.tests.test_auth_rbac import build_test_client

    client, _ = build_test_client()
    response = client.get("/health")

    # Deep health probes the DB (up on test SQLite); redis is absent in tests.
    assert response.status_code == 200
    assert response.json()["status"] in ("ok", "degraded")
    assert response.json()["checks"]["db"] == "up"
    assert response.json()["requestId"]
    assert response.headers["x-request-id"] == response.json()["requestId"]


def test_celery_queues_are_registered():
    from server.app.tasks.celery_app import QUEUE_NAMES, celery_app

    assert QUEUE_NAMES == ("parse", "qa", "embedding", "maintenance")
    assert {queue.name for queue in celery_app.conf.task_queues} == set(QUEUE_NAMES)

