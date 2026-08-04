from sqlalchemy import select

from server.tests.test_auth_rbac import build_test_client
from server.tests.test_model_config import login_admin


def test_adaptive_chunking_log_is_structured_and_excludes_document_content(caplog):
    from dataclasses import dataclass

    from server.app.services.chunking import (
        AtomicBlock,
        BlockType,
        ChunkPolicy,
        ChunkingService,
    )
    from server.app.services.document_parse_service import log_chunking_observability

    @dataclass(frozen=True)
    class Counter:
        name: str = "observability-test-counter"
        version: str = "1.0"

        def count(self, text: str) -> int:
            return len(text.split())

        def split_by_token_limit(self, text: str, limit: int) -> list[str]:
            words = text.split()
            return [
                " ".join(words[index : index + limit])
                for index in range(0, len(words), limit)
            ]

    counter = Counter()
    policy = ChunkPolicy(
        tokenizer_name=counter.name,
        tokenizer_version=counter.version,
        min_tokens=2,
        target_tokens=3,
        max_tokens=4,
        overlap_tokens=0,
        parent_max_tokens=8,
        embedding_provider_input_limit=16,
    )
    result = ChunkingService(counter).chunk(
        [
            AtomicBlock(
                index=0,
                content="private-customer-content must-never-appear-in-logs alpha beta",
                block_type=BlockType.TEXT,
                source_locator={"block": 0},
                page_no=1,
                title_path=("Private",),
                structural_id="block-0",
                parent_structural_id="section-0",
            )
        ],
        policy,
        document_title="Private Document",
    )

    with caplog.at_level("INFO", logger="server.app.services.document_parse_service"):
        log_chunking_observability(
            tenant_id="tenant-1",
            document_id="document-1",
            job_id="job-1",
            parser_name="MARKDOWN",
            parser_version="1.0",
            policy=policy,
            result=result,
            duration_seconds=0.125,
        )

    record = next(
        record for record in caplog.records if record.message == "adaptive chunking completed"
    )
    assert record.tenant_id == "tenant-1"
    assert record.document_id == "document-1"
    assert record.job_id == "job-1"
    assert record.config_hash == policy.config_hash
    assert record.chunker_version == policy.version
    assert record.atomic_block_count == 1
    assert record.child_count == result.stats.child_count
    assert record.parent_count == result.stats.parent_count
    assert record.tokenizerName == counter.name
    assert record.mergeCount == result.stats.merge_count
    assert record.splitCount == result.stats.split_count
    assert record.tinyChunkCount == 0
    assert record.oversizedChunkCount == result.stats.oversized_count
    assert record.skippedImageCount == 0
    assert record.featureFlags == {"adaptiveChunkingEnabled": True}
    assert "private-customer-content" not in record.getMessage()
    assert "private-customer-content" not in str(record.__dict__)


def test_adaptive_chunking_metrics_use_pipeline_event_counts():
    from dataclasses import dataclass

    from server.app.core import metrics
    from server.app.services.chunking import (
        AtomicBlock,
        BlockType,
        ChunkPolicy,
        ChunkingService,
    )
    from server.app.services.document_parse_service import log_chunking_observability

    @dataclass(frozen=True)
    class Counter:
        name: str = "observability-event-counter"
        version: str = "1.0"

        def count(self, text: str) -> int:
            return len(text.split())

        def split_by_token_limit(self, text: str, limit: int) -> list[str]:
            words = text.split()
            return [
                " ".join(words[index : index + limit])
                for index in range(0, len(words), limit)
            ]

    counter = Counter()
    policy = ChunkPolicy(
        tokenizer_name=counter.name,
        tokenizer_version=counter.version,
        min_tokens=2,
        target_tokens=3,
        max_tokens=4,
        overlap_tokens=0,
        parent_max_tokens=8,
        embedding_provider_input_limit=16,
    )
    result = ChunkingService(counter).chunk(
        [
            AtomicBlock(
                index=0,
                content="alpha",
                block_type=BlockType.TEXT,
                source_locator={"block": 0},
                page_no=1,
                title_path=("Guide",),
                structural_id="block-0",
                parent_structural_id="section-0",
            ),
            AtomicBlock(
                index=1,
                content="beta",
                block_type=BlockType.TEXT,
                source_locator={"block": 1},
                page_no=1,
                title_path=("Guide",),
                structural_id="block-1",
                parent_structural_id="section-0",
            ),
            AtomicBlock(
                index=2,
                content="one two three four five six seven eight",
                block_type=BlockType.TEXT,
                source_locator={"block": 2},
                page_no=1,
                title_path=("Guide",),
                structural_id="block-2",
                parent_structural_id="section-0",
                metadata={"hard_boundary": True},
            ),
        ],
        policy,
        document_title="Guide",
    )

    metrics.reset()
    log_chunking_observability(
        tenant_id="tenant-1",
        document_id="document-1",
        job_id="job-1",
        parser_name="MARKDOWN",
        parser_version="1.0",
        policy=policy,
        result=result,
        duration_seconds=0.125,
    )

    rendered = metrics.render_prometheus()
    assert "lingxi_chunk_merge_total 1" in rendered
    assert "lingxi_chunk_oversized_total 1" in rendered
    assert "lingxi_chunk_split_total 2" in rendered


def test_logs_api_lists_filters_and_redacts_sensitive_fields():
    client, SessionLocal = build_test_client()
    headers = login_admin(client)

    from server.app.models.import_job import ImportJob
    from server.app.models.logs import ApiCallLog, AuditLog, TaskRun
    from server.app.models.model_config import ModelCallLog, ModelProvider

    with SessionLocal() as session:
        tenant_id = _tenant_id(session)
        provider = ModelProvider(
            tenant_id=tenant_id,
            provider_type="OPENAI_COMPATIBLE",
            name="Mock Provider",
            base_url="mock://success",
            encrypted_api_key="sk-should-not-leak",
            status="ACTIVE",
        )
        job = ImportJob(
            tenant_id=tenant_id,
            status="FAILED",
            stage="PARSING",
            progress=40,
            retry_count=0,
            max_retries=3,
            error_code="PARSE_FAILED",
            error_message="parser failed",
        )
        session.add_all([provider, job])
        session.flush()
        provider_id = provider.id
        task_run = TaskRun(
            tenant_id=tenant_id,
            task_type="parse_document",
            queue_name="parse",
            resource_type="IMPORT_JOB",
            resource_id=job.id,
            stage="PARSING",
            status="FAILED",
            error={"code": "PARSE_FAILED", "apiKey": "lk_live_secret"},
            request_id="req-task-1",
        )
        session.add_all(
            [
                task_run,
                ModelCallLog(
                    tenant_id=tenant_id,
                    provider_id=provider.id,
                    run_id="run-1",
                    batch_id="0:batch-1",
                    batch_index="0",
                    retry_count=1,
                    split_depth=2,
                    input_char_count=120,
                    estimated_input_tokens=48,
                    output_char_count=80,
                    estimated_output_tokens=30,
                    timeout_phase="read",
                    endpoint=(
                        "https://api.example.com/v1/chat/completions"
                        "?api_key=endpoint-secret"
                    ),
                    model_name_snapshot="gpt-x",
                    capability="CHAT",
                    status="FAILED",
                    latency_ms=123,
                    token_usage={"prompt": 10, "completion": 0},
                    error_code="MODEL_DOWN",
                    error_message="Authorization: Bearer secret",
                    request_id="req-model-1",
                ),
                ApiCallLog(
                    tenant_id=tenant_id,
                    key_prefix="lk_live_abcd",
                    path="/v1/chat/completions",
                    method="POST",
                    status_code=500,
                    latency_ms=45,
                    error_code="UPSTREAM_ERROR",
                    request_id="req-api-1",
                    request_metadata={"Authorization": "Bearer secret"},
                ),
                AuditLog(
                    tenant_id=tenant_id,
                    actor_id="user-1",
                    action="SETTING_UPDATED",
                    resource_type="SYSTEM_SETTING",
                    resource_id="settings",
                    before_snapshot={"apiKey": "before-secret"},
                    after_snapshot={"value": "ok"},
                    request_id="req-audit-1",
                ),
            ]
        )
        session.commit()

    task_logs = client.get(
        "/api/v1/logs/task-runs?status=FAILED&requestId=req-task-1",
        headers=headers,
    )
    assert task_logs.status_code == 200
    assert task_logs.json()["data"][0]["retryable"] is True
    assert "lk_live_secret" not in task_logs.text
    assert task_logs.json()["data"][0]["error"]["apiKey"] == "***REDACTED***"

    model_logs = client.get("/api/v1/logs/model-calls?runId=run-1", headers=headers)
    assert model_logs.status_code == 200
    assert model_logs.json()["data"][0]["providerName"] == "Mock Provider"
    assert model_logs.json()["data"][0]["batchId"] == "0:batch-1"
    assert model_logs.json()["data"][0]["batchIndex"] == "0"
    assert model_logs.json()["data"][0]["retryCount"] == 1
    assert model_logs.json()["data"][0]["timeoutPhase"] == "read"
    assert model_logs.json()["data"][0]["modelNameSnapshot"] == "gpt-x"
    assert "endpoint-secret" not in model_logs.text
    assert "secret" not in model_logs.text

    filtered_logs = client.get(
        "/api/v1/logs/model-calls"
        "?batchId=0%3Abatch-1&timeoutPhase=read"
        f"&providerId={provider_id}",
        headers=headers,
    )
    assert filtered_logs.status_code == 200
    assert filtered_logs.json()["pagination"]["totalItems"] == 1

    api_logs = client.get("/api/v1/logs/api-calls?requestId=req-api-1", headers=headers)
    assert api_logs.status_code == 200
    assert api_logs.json()["data"][0]["requestMetadata"]["Authorization"] == "***REDACTED***"

    audit_logs = client.get("/api/v1/logs/audit?requestId=req-audit-1", headers=headers)
    assert audit_logs.status_code == 200
    assert audit_logs.json()["data"][0]["beforeSnapshot"]["apiKey"] == "***REDACTED***"


def test_api_call_log_middleware_records_admin_and_failed_calls():
    client, SessionLocal = build_test_client()
    headers = login_admin(client)

    from server.app.models.logs import ApiCallLog

    # An authenticated admin call must be attributed to the caller's tenant.
    admin_call = client.get("/api/v1/api-keys", headers=headers)
    assert admin_call.status_code == 200

    # An external gateway call with a bogus key fails auth and has no tenant.
    failed_call = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer lk_live_bogus_key_0000"},
        json={
            "model": "knowledge-chat",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )
    assert failed_call.status_code == 401

    with SessionLocal() as session:
        tenant_id = _tenant_id(session)
        admin_log = session.scalar(
            select(ApiCallLog).where(ApiCallLog.path == "/api/v1/api-keys")
        )
        failed_log = session.scalar(
            select(ApiCallLog).where(ApiCallLog.path == "/v1/chat/completions")
        )

    # The middleware — not the endpoint — recorded the admin call, with tenant.
    assert admin_log is not None
    assert admin_log.method == "GET"
    assert admin_log.status_code == 200
    assert admin_log.tenant_id == tenant_id

    # Failed auth lands with a NULL tenant...
    assert failed_log is not None
    assert failed_log.tenant_id is None

    # ...and is still visible in the console (NULL-tenant rows are included).
    listed = client.get("/api/v1/logs/api-calls", headers=headers)
    assert listed.status_code == 200
    paths = [row["path"] for row in listed.json()["data"]]
    assert "/v1/chat/completions" in paths
    assert "/api/v1/api-keys" in paths


def test_retry_task_run_requeues_failed_import_job(monkeypatch):
    client, SessionLocal = build_test_client()
    headers = login_admin(client)

    from server.app.models.document import Document
    from server.app.models.import_job import ImportJob
    from server.app.models.logs import TaskRun
    from server.app.services import import_service

    requeued: list[str] = []
    monkeypatch.setattr(
        import_service, "enqueue_parse_task", lambda job_id: requeued.append(job_id)
    )

    with SessionLocal() as session:
        tenant_id = _tenant_id(session)
        document = Document(
            tenant_id=tenant_id,
            title="Retry Doc",
            file_name="retry.md",
            file_type="MARKDOWN",
            mime_type="text/markdown",
            file_size=100,
            object_key="tenant/retry.md",
            checksum="sha256:retry",
            status="FAILED",
        )
        session.add(document)
        session.flush()
        job = ImportJob(
            tenant_id=tenant_id,
            document_id=document.id,
            status="FAILED",
            stage="PARSING",
            progress=40,
            retry_count=0,
            max_retries=3,
            error_code="PARSE_FAILED",
            error_message="parser failed",
        )
        session.add(job)
        session.flush()
        job_id = job.id
        task_run = TaskRun(
            tenant_id=tenant_id,
            task_type="parse_document",
            queue_name="parse",
            resource_type="IMPORT_JOB",
            resource_id=job.id,
            stage="PARSING",
            status="FAILED",
            error={"code": "PARSE_FAILED"},
            request_id="req-task-2",
        )
        session.add(task_run)
        session.commit()
        task_run_id = task_run.id

    response = client.post(f"/api/v1/task-runs/{task_run_id}/retry", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "RUNNING"
    assert response.json()["retryCount"] == 1
    assert requeued == [job_id]  # the parse task was actually re-enqueued


def _tenant_id(session) -> str:
    from server.app.models.user import Tenant

    return session.scalar(select(Tenant.id))
