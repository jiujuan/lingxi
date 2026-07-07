from sqlalchemy import select

from server.tests.test_auth_rbac import build_test_client
from server.tests.test_model_config import login_admin


def login_employee(client) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "employee@example.com", "password": "Employee123!"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def seed_document_center_data(SessionLocal):
    from server.app.models.document import (
        Document,
        DocumentAccessRule,
        DocumentAccessSubjectType,
        DocumentStatus,
    )
    from server.app.models.import_job import ImportJob, ImportJobStatus
    from server.app.models.logs import TaskRun
    from server.app.models.qa_pair import DocumentChunk, QaPair
    from server.app.models.user import Department, Tenant

    with SessionLocal() as session:
        tenant = session.scalar(select(Tenant))
        support = session.scalar(select(Department).where(Department.code == "SUPPORT"))
        private = session.scalar(select(Department).where(Department.code == "PRIVATE"))

        ready_doc = Document(
            tenant_id=tenant.id,
            title="Refund SOP",
            file_name="refund.md",
            file_type="MARKDOWN",
            mime_type="text/markdown",
            file_size=120,
            object_key="uploads/refund.md",
            checksum="refund-checksum",
            status=DocumentStatus.READY,
            parser_name="LIGHTWEIGHT",
            parser_version="1.0",
            page_count=2,
            qa_pair_count=1,
            chunk_count=1,
        )
        private_doc = Document(
            tenant_id=tenant.id,
            title="Private Playbook",
            file_name="private.md",
            file_type="MARKDOWN",
            mime_type="text/markdown",
            file_size=80,
            object_key="uploads/private.md",
            checksum="private-checksum",
            status=DocumentStatus.READY,
        )
        failed_doc = Document(
            tenant_id=tenant.id,
            title="Broken Manual",
            file_name="broken.pdf",
            file_type="PDF",
            mime_type="application/pdf",
            file_size=300,
            object_key="uploads/broken.pdf",
            checksum="broken-checksum",
            status=DocumentStatus.FAILED,
            last_error_code="PARSER_UNAVAILABLE",
            last_error_message="MinerU 解析器尚未配置",
        )
        session.add_all([ready_doc, private_doc, failed_doc])
        session.flush()

        ready_job = ImportJob(
            tenant_id=tenant.id,
            document_id=ready_doc.id,
            status=ImportJobStatus.COMPLETED.value,
            stage="COMPLETED",
            progress=100,
        )
        failed_job = ImportJob(
            tenant_id=tenant.id,
            document_id=failed_doc.id,
            status=ImportJobStatus.FAILED.value,
            stage="PARSING",
            progress=20,
            retry_count=1,
            error_code="PARSER_UNAVAILABLE",
            error_message="MinerU 解析器尚未配置",
        )
        session.add_all([ready_job, failed_job])
        session.flush()

        chunk = DocumentChunk(
            tenant_id=tenant.id,
            document_id=ready_doc.id,
            job_id=ready_job.id,
            chunk_index=0,
            title_path=["退款流程"],
            content="退款需要主管审批。",
            page_no=1,
            token_count=4,
            source_locator={"lineStart": 1},
        )
        session.add(chunk)
        session.flush()
        session.add(
            QaPair(
                tenant_id=tenant.id,
                document_id=ready_doc.id,
                chunk_id=chunk.id,
                job_id=ready_job.id,
                pair_index=0,
                question="退款需要谁审批？",
                answer="退款需要主管审批。",
                quote="退款需要主管审批。",
                page_no=1,
                question_embedding=[0.1, 0.2, 0.3, 0.4],
                search_text="退款 需要 主管 审批",
                status="ACTIVE",
            )
        )

        session.add_all(
            [
                DocumentAccessRule(
                    tenant_id=tenant.id,
                    document_id=ready_doc.id,
                    subject_type=DocumentAccessSubjectType.ALL_AUTHENTICATED,
                    subject_id=None,
                ),
                DocumentAccessRule(
                    tenant_id=tenant.id,
                    document_id=private_doc.id,
                    subject_type=DocumentAccessSubjectType.DEPARTMENT,
                    subject_id=private.id,
                ),
                DocumentAccessRule(
                    tenant_id=tenant.id,
                    document_id=failed_doc.id,
                    subject_type=DocumentAccessSubjectType.DEPARTMENT,
                    subject_id=support.id,
                ),
                TaskRun(
                    tenant_id=tenant.id,
                    task_type="parse_document_task",
                    queue_name="parse",
                    resource_type="IMPORT_JOB",
                    resource_id=failed_job.id,
                    stage="PARSING",
                    status="FAILED",
                    error={
                        "code": "PARSER_UNAVAILABLE",
                        "message": "MinerU 解析器尚未配置",
                        "retryable": True,
                    },
                    request_id="req_failed_parse",
                ),
            ]
        )
        session.commit()
        return {
            "ready_document_id": ready_doc.id,
            "private_document_id": private_doc.id,
            "failed_document_id": failed_doc.id,
            "failed_job_id": failed_job.id,
            "support_department_id": support.id,
        }


def test_document_list_detail_and_chunks_follow_document_center_contract():
    client, SessionLocal = build_test_client()
    admin_headers = login_admin(client)
    employee_headers = login_employee(client)
    ids = seed_document_center_data(SessionLocal)

    listed = client.get(
        "/api/v1/documents?keyword=refund&status=READY&page=1&pageSize=10",
        headers=admin_headers,
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["pagination"]["totalItems"] == 1
    assert body["data"][0]["title"] == "Refund SOP"
    assert body["data"][0]["latestJob"]["stage"] == "COMPLETED"
    assert body["data"][0]["permissions"]["allAuthenticated"] is True

    employee_list = client.get("/api/v1/documents?page=1&pageSize=20", headers=employee_headers)
    assert employee_list.status_code == 200
    employee_titles = {item["title"] for item in employee_list.json()["data"]}
    assert "Refund SOP" in employee_titles
    assert "Private Playbook" not in employee_titles

    detail = client.get(
        f"/api/v1/documents/{ids['ready_document_id']}",
        headers=admin_headers,
    )
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["id"] == ids["ready_document_id"]
    assert detail_body["chunkCount"] == 1
    assert detail_body["latestJob"]["progress"] == 100

    chunks = client.get(
        f"/api/v1/documents/{ids['ready_document_id']}/chunks?page=1&pageSize=10",
        headers=admin_headers,
    )
    assert chunks.status_code == 200
    assert chunks.json()["data"][0]["content"] == "退款需要主管审批。"
    assert chunks.json()["data"][0]["titlePath"] == ["退款流程"]

    failed_detail = client.get(
        f"/api/v1/documents/{ids['failed_document_id']}",
        headers=admin_headers,
    )
    assert failed_detail.status_code == 200
    assert failed_detail.json()["lastErrorCode"] == "PARSER_UNAVAILABLE"
    assert failed_detail.json()["processingLogs"][0]["requestId"] == "req_failed_parse"


def test_permissions_update_and_delete_write_audit_and_change_visibility():
    client, SessionLocal = build_test_client()
    admin_headers = login_admin(client)
    employee_headers = login_employee(client)
    ids = seed_document_center_data(SessionLocal)

    permission_update = client.patch(
        f"/api/v1/documents/{ids['private_document_id']}/permissions",
        headers=admin_headers,
        json={
            "departmentIds": [ids["support_department_id"]],
            "roleIds": [],
            "userIds": [],
            "allAuthenticated": False,
        },
    )
    assert permission_update.status_code == 200
    assert permission_update.json()["departments"][0]["id"] == ids["support_department_id"]

    employee_list = client.get("/api/v1/documents?page=1&pageSize=20", headers=employee_headers)
    employee_titles = {item["title"] for item in employee_list.json()["data"]}
    assert "Private Playbook" in employee_titles

    deleted = client.delete(
        f"/api/v1/documents/{ids['private_document_id']}",
        headers=admin_headers,
    )
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "DELETED"

    listed_after_delete = client.get("/api/v1/documents?page=1&pageSize=20", headers=admin_headers)
    titles_after_delete = {item["title"] for item in listed_after_delete.json()["data"]}
    assert "Private Playbook" not in titles_after_delete

    from server.app.models.logs import AuditLog

    with SessionLocal() as session:
        actions = {
            log.action
            for log in session.scalars(
                select(AuditLog).where(AuditLog.resource_id == ids["private_document_id"])
            ).all()
        }

    assert {"DOCUMENT_PERMISSION_UPDATED", "DOCUMENT_DELETED"}.issubset(actions)


def test_retry_failed_import_job_uses_failed_stage_and_clears_error(monkeypatch):
    client, SessionLocal = build_test_client()
    admin_headers = login_admin(client)
    ids = seed_document_center_data(SessionLocal)
    queued: list[str] = []

    from server.app.services import import_service

    monkeypatch.setattr(import_service, "enqueue_parse_task", lambda job_id: queued.append(job_id))

    response = client.post(
        f"/api/v1/import-jobs/{ids['failed_job_id']}/retries",
        headers=admin_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "RUNNING"
    assert body["stage"] == "PARSING"
    assert body["retryCount"] == 2
    assert body["errorCode"] is None
    assert body["retryable"] is False
    assert queued == [ids["failed_job_id"]]
