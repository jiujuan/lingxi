from server.tests.test_auth_rbac import build_test_client


def test_configure_logging_preserves_external_root_handlers():
    import logging

    from server.app.core.logging import configure_logging

    root = logging.getLogger()
    original_handlers = tuple(root.handlers)
    original_level = root.level
    sentinel = logging.NullHandler()
    for handler in original_handlers:
        root.removeHandler(handler)
    root.addHandler(sentinel)
    try:
        configure_logging()

        assert sentinel in root.handlers
    finally:
        for handler in tuple(root.handlers):
            root.removeHandler(handler)
            if handler is not sentinel:
                handler.close()
        root.setLevel(original_level)
        for handler in original_handlers:
            root.addHandler(handler)


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


def test_chunking_and_retrieval_metrics_are_low_cardinality():
    from server.app.core import metrics

    metrics.reset()
    metrics.observe_chunking(
        duration_seconds=0.125,
        token_counts_by_block_type={"TEXT": [3, 8], "TABLE": [5]},
        tiny_count=1,
        oversized_count=2,
        merge_count=3,
        split_count=4,
    )
    metrics.observe_qa_provenance_validation_failure("QA_PROVENANCE_QUOTE_MISMATCH")
    metrics.observe_qa_chunk_coverage_ratio(0.75)
    metrics.observe_embedding_targets("QA", "success", 2)
    metrics.observe_embedding_targets("CHUNK", "failed", 1)
    metrics.observe_retrieval(
        candidate_counts={"qa_vector": 2, "chunk_text": 1},
        channel_hit_ratios={"qa_vector": 1.0, "chunk_text": 0.5},
        dedup_ratio=0.25,
        hydration_tokens=42,
        latency_by_stage_seconds={"retrieve": 0.2, "rerank": 0.03},
        degraded_reason="chunk_channel_unavailable",
    )

    text = metrics.render_prometheus()

    for metric in (
        "lingxi_chunking_duration_seconds",
        "lingxi_chunk_tokens",
        "lingxi_chunk_tiny_total",
        "lingxi_chunk_oversized_total",
        "lingxi_chunk_merge_total",
        "lingxi_chunk_split_total",
        "lingxi_qa_provenance_validation_failure_total",
        "lingxi_qa_chunk_coverage_ratio",
        "lingxi_embedding_targets_total",
        "lingxi_retrieval_candidates_total",
        "lingxi_retrieval_channel_hit_ratio",
        "lingxi_retrieval_dedup_ratio",
        "lingxi_retrieval_hydration_tokens",
        "lingxi_retrieval_latency_seconds",
        "lingxi_retrieval_degraded_total",
    ):
        assert metric in text
    assert (
        'lingxi_qa_provenance_validation_failure_total{reason="QA_PROVENANCE_QUOTE_MISMATCH"} 1'
        in text
    )
    assert 'lingxi_embedding_targets_total{status="success",type="QA"} 2' in text
    assert 'lingxi_retrieval_degraded_total{reason="chunk_channel_unavailable"} 1' in text
    assert "document-1" not in text
    assert "private-customer-question" not in text


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
