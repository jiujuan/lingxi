from sqlalchemy import select

from server.tests.test_auth_rbac import build_test_client
from server.tests.test_model_config import login_admin


def test_dashboard_summary_returns_zero_state_and_aggregates_data():
    client, SessionLocal = build_test_client()
    headers = login_admin(client)

    zero = client.get("/api/v1/dashboard/summary", headers=headers)
    assert zero.status_code == 200
    assert zero.json()["metrics"]["documentCount"] == 0
    assert zero.json()["ingestionHealth"]["successRate"] == 0

    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob
    from server.app.models.logs import ApiCallLog
    from server.app.models.qa_pair import QaPair

    with SessionLocal() as session:
        tenant_id = _tenant_id(session)
        document = Document(
            tenant_id=tenant_id,
            title="Handbook",
            file_name="handbook.md",
            file_type="MARKDOWN",
            mime_type="text/markdown",
            file_size=100,
            object_key="tenant/handbook.md",
            checksum="sha256:handbook",
            status=DocumentStatus.READY,
            qa_pair_count=1,
        )
        session.add(document)
        session.flush()
        session.add_all(
            [
                QaPair(
                    tenant_id=tenant_id,
                    document_id=document.id,
                    question="Q",
                    answer="A",
                    quote="A",
                    pair_index=1,
                    status="ACTIVE",
                ),
                ImportJob(
                    tenant_id=tenant_id,
                    document_id=document.id,
                    status="COMPLETED",
                    stage="COMPLETED",
                    progress=100,
                ),
                ImportJob(
                    tenant_id=tenant_id,
                    document_id=document.id,
                    status="FAILED",
                    stage="EMBEDDING",
                    progress=80,
                    error_code="EMBEDDING_FAILED",
                ),
                ApiCallLog(
                    tenant_id=tenant_id,
                    key_prefix="lk_live_abcd",
                    path="/v1/chat/completions",
                    method="POST",
                    status_code=200,
                    latency_ms=30,
                ),
            ]
        )
        session.commit()

    summary = client.get("/api/v1/dashboard/summary", headers=headers)
    assert summary.status_code == 200
    body = summary.json()
    assert body["metrics"]["documentCount"] == 1
    assert body["metrics"]["qaPairCount"] == 1
    assert body["metrics"]["apiCallCount"] == 1
    assert body["metrics"]["taskSuccessRate"] == 50
    assert "FAILED" in {item["status"] for item in body["recentTasks"]}
    assert body["riskEvents"][0]["type"] == "IMPORT_JOB_FAILED"


def test_settings_read_save_validate_and_audit():
    client, SessionLocal = build_test_client()
    headers = login_admin(client)

    from server.app.models.logs import AuditLog, SystemSetting

    defaults = client.get("/api/v1/settings", headers=headers)
    assert defaults.status_code == 200
    assert defaults.json()["filePolicy"]["maxFileSizeMb"] > 0

    invalid = client.put(
        "/api/v1/settings",
        headers=headers,
        json={
            **defaults.json(),
            "retrievalPolicy": {
                **defaults.json()["retrievalPolicy"],
                "lowConfidenceThreshold": 3,
            },
        },
    )
    assert invalid.status_code == 422

    payload = defaults.json()
    payload["filePolicy"]["maxFileSizeMb"] = 20
    payload["retrievalPolicy"]["finalTopK"] = 6
    payload["retentionPolicy"]["apiCallLogDays"] = 60

    saved = client.put("/api/v1/settings", headers=headers, json=payload)
    assert saved.status_code == 200
    assert saved.json()["filePolicy"]["maxFileSizeMb"] == 20
    assert saved.json()["effectiveScopes"]["filePolicy"] == "NEW_TASKS"

    with SessionLocal() as session:
        setting = session.scalar(select(SystemSetting))
        audit = session.scalar(select(AuditLog).where(AuditLog.action == "SYSTEM_SETTINGS_UPDATED"))

    assert setting is not None
    assert setting.value["filePolicy"]["maxFileSizeMb"] == 20
    assert audit is not None


def _tenant_id(session) -> str:
    from server.app.models.user import Tenant

    return session.scalar(select(Tenant.id))
