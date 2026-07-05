from sqlalchemy import select

from server.tests.test_auth_rbac import build_test_client
from server.tests.test_model_config import login_admin


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
    assert "secret" not in model_logs.text

    api_logs = client.get("/api/v1/logs/api-calls?requestId=req-api-1", headers=headers)
    assert api_logs.status_code == 200
    assert api_logs.json()["data"][0]["requestMetadata"]["Authorization"] == "***REDACTED***"

    audit_logs = client.get("/api/v1/logs/audit?requestId=req-audit-1", headers=headers)
    assert audit_logs.status_code == 200
    assert audit_logs.json()["data"][0]["beforeSnapshot"]["apiKey"] == "***REDACTED***"


def test_retry_task_run_requeues_failed_import_job():
    client, SessionLocal = build_test_client()
    headers = login_admin(client)

    from server.app.models.document import Document
    from server.app.models.import_job import ImportJob
    from server.app.models.logs import TaskRun

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


def _tenant_id(session) -> str:
    from server.app.models.user import Tenant

    return session.scalar(select(Tenant.id))
