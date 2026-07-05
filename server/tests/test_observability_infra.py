from server.tests.test_auth_rbac import build_test_client


def test_health_reports_dependency_checks():
    client, _ = build_test_client()
    response = client.get("/health")

    # DB is up (test SQLite); redis is absent in tests -> degraded but 200.
    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["db"] == "up"
    assert body["checks"]["redis"] in ("up", "down")
    assert body["status"] in ("ok", "degraded")
    assert body["requestId"]


def test_metrics_endpoint_exposes_prometheus_text():
    client, _ = build_test_client()
    client.get("/health")  # generate at least one recorded request
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    text = response.text
    assert "lingxi_http_requests_total" in text
    assert "lingxi_http_request_duration_seconds_bucket" in text
    assert 'path="/health"' in text


def test_json_log_formatter_includes_request_id():
    import json
    import logging

    from server.app.core.ids import set_request_id
    from server.app.core.logging import JsonFormatter, RequestIdFilter

    set_request_id("req_test_123")
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello %s", args=("world",), exc_info=None,
    )
    RequestIdFilter().filter(record)
    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "hello world"
    assert payload["requestId"] == "req_test_123"
    assert payload["level"] == "INFO"
