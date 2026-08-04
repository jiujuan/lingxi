from datetime import UTC, datetime

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
    from server.app.models.knowledge_category import KnowledgeCategory, KnowledgeSpace
    from server.app.models.logs import TaskRun
    from server.app.models.qa_pair import DocumentChunk, QaPair
    from server.app.models.user import Department, Tenant

    with SessionLocal() as session:
        tenant = session.scalar(select(Tenant))
        support = session.scalar(select(Department).where(Department.code == "SUPPORT"))
        private = session.scalar(select(Department).where(Department.code == "PRIVATE"))

        support_space = KnowledgeSpace(
            tenant_id=tenant.id,
            name="客服知识库",
            code="support-kb",
        )
        private_space = KnowledgeSpace(
            tenant_id=tenant.id,
            name="内部知识库",
            code="internal-kb",
        )
        session.add_all([support_space, private_space])
        session.flush()

        refund_category = KnowledgeCategory(
            tenant_id=tenant.id,
            space_id=support_space.id,
            department_id=support.id,
            name="退款专题",
            code="refund",
        )
        private_category = KnowledgeCategory(
            tenant_id=tenant.id,
            space_id=private_space.id,
            department_id=private.id,
            name="内部制度",
            code="policy",
        )
        session.add_all([refund_category, private_category])
        session.flush()

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
            knowledge_space_id=support_space.id,
            category_department_id=support.id,
            knowledge_category_id=refund_category.id,
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
            knowledge_space_id=private_space.id,
            category_department_id=private.id,
            knowledge_category_id=private_category.id,
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
            "private_department_id": private.id,
            "support_space_id": support_space.id,
            "private_space_id": private_space.id,
            "refund_category_id": refund_category.id,
            "private_category_id": private_category.id,
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
    classification = body["data"][0]["classification"]
    assert classification["knowledgeSpaceId"] == ids["support_space_id"]
    assert classification["categoryDepartmentId"] == ids["support_department_id"]
    assert classification["knowledgeCategoryId"] == ids["refund_category_id"]
    assert classification["knowledgeSpace"] == {
        "id": ids["support_space_id"],
        "name": "客服知识库",
        "code": "support-kb",
    }
    assert classification["categoryDepartment"]["code"] == "SUPPORT"
    assert classification["knowledgeCategory"]["name"] == "退款专题"

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
    assert detail_body["classification"]["knowledgeCategoryId"] == ids[
        "refund_category_id"
    ]
    assert detail_body["classification"]["knowledgeCategory"]["code"] == "refund"

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
    failed_body = failed_detail.json()
    assert failed_body["lastErrorCode"] == "PARSER_UNAVAILABLE"
    assert failed_body["processingLogs"][0]["requestId"] == "req_failed_parse"
    assert failed_body["classification"] is None


def test_document_list_supports_classification_filters_without_permission_leakage():
    client, SessionLocal = build_test_client()
    admin_headers = login_admin(client)
    employee_headers = login_employee(client)
    ids = seed_document_center_data(SessionLocal)

    by_space = client.get(
        f"/api/v1/documents?spaceId={ids['support_space_id']}&pageSize=20",
        headers=admin_headers,
    )
    assert by_space.status_code == 200
    assert {item["title"] for item in by_space.json()["data"]} == {"Refund SOP"}

    by_department = client.get(
        "/api/v1/documents"
        f"?classificationDepartmentId={ids['private_department_id']}&pageSize=20",
        headers=admin_headers,
    )
    assert by_department.status_code == 200
    assert {item["title"] for item in by_department.json()["data"]} == {
        "Private Playbook"
    }

    by_category = client.get(
        f"/api/v1/documents?categoryId={ids['refund_category_id']}&pageSize=20",
        headers=admin_headers,
    )
    assert by_category.status_code == 200
    assert {item["title"] for item in by_category.json()["data"]} == {
        "Refund SOP"
    }

    employee_private_category = client.get(
        f"/api/v1/documents?categoryId={ids['private_category_id']}&pageSize=20",
        headers=employee_headers,
    )
    assert employee_private_category.status_code == 200
    assert employee_private_category.json()["data"] == []

    mixed_department_filters = client.get(
        "/api/v1/documents"
        f"?departmentId={ids['support_department_id']}"
        f"&classificationDepartmentId={ids['private_department_id']}"
        "&pageSize=20",
        headers=admin_headers,
    )
    assert mixed_department_filters.status_code == 200
    assert mixed_department_filters.json()["data"] == []


def test_document_list_supports_unclassified_filter():
    client, SessionLocal = build_test_client()
    admin_headers = login_admin(client)
    employee_headers = login_employee(client)
    ids = seed_document_center_data(SessionLocal)

    admin_result = client.get(
        "/api/v1/documents?isUnclassified=true&pageSize=20",
        headers=admin_headers,
    )
    assert admin_result.status_code == 200
    assert {item["title"] for item in admin_result.json()["data"]} == {
        "Broken Manual"
    }
    assert admin_result.json()["data"][0]["classification"] is None

    employee_result = client.get(
        "/api/v1/documents?isUnclassified=true&pageSize=20",
        headers=employee_headers,
    )
    assert employee_result.status_code == 200
    assert {item["id"] for item in employee_result.json()["data"]} == {
        ids["failed_document_id"]
    }


def test_bulk_document_classification_updates_and_clears_atomically():
    client, SessionLocal = build_test_client()
    admin_headers = login_admin(client)
    ids = seed_document_center_data(SessionLocal)

    updated = client.patch(
        "/api/v1/documents/bulk-classification",
        headers=admin_headers,
        json={
            "documentIds": [ids["ready_document_id"], ids["failed_document_id"]],
            "classification": {
                "spaceId": ids["private_space_id"],
                "departmentId": ids["private_department_id"],
                "categoryId": ids["private_category_id"],
            },
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["updatedCount"] == 2
    assert body["documentIds"] == [
        ids["ready_document_id"],
        ids["failed_document_id"],
    ]
    assert body["classification"]["knowledgeCategoryId"] == ids["private_category_id"]

    by_category = client.get(
        f"/api/v1/documents?categoryId={ids['private_category_id']}&pageSize=20",
        headers=admin_headers,
    )
    assert by_category.status_code == 200
    assert {item["title"] for item in by_category.json()["data"]} == {
        "Refund SOP",
        "Private Playbook",
        "Broken Manual",
    }

    cleared = client.patch(
        "/api/v1/documents/bulk-classification",
        headers=admin_headers,
        json={
            "documentIds": [ids["ready_document_id"], ids["failed_document_id"]],
            "classification": None,
        },
    )
    assert cleared.status_code == 200
    assert cleared.json()["updatedCount"] == 2
    assert cleared.json()["classification"] is None

    unclassified = client.get(
        "/api/v1/documents?isUnclassified=true&pageSize=20",
        headers=admin_headers,
    )
    assert unclassified.status_code == 200
    assert {item["id"] for item in unclassified.json()["data"]} == {
        ids["ready_document_id"],
        ids["failed_document_id"],
    }


def test_bulk_document_classification_rejects_inaccessible_document_without_partial_update():
    client, SessionLocal = build_test_client()
    employee_headers = login_employee(client)
    ids = seed_document_center_data(SessionLocal)

    response = client.patch(
        "/api/v1/documents/bulk-classification",
        headers=employee_headers,
        json={
            "documentIds": [ids["ready_document_id"], ids["private_document_id"]],
            "classification": None,
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"

    from server.app.models.document import Document

    with SessionLocal() as session:
        ready = session.get(Document, ids["ready_document_id"])
        private = session.get(Document, ids["private_document_id"])
        assert ready.knowledge_category_id == ids["refund_category_id"]
        assert private.knowledge_category_id == ids["private_category_id"]


def test_document_classification_update_validates_path_and_writes_audit():
    client, SessionLocal = build_test_client()
    admin_headers = login_admin(client)
    ids = seed_document_center_data(SessionLocal)

    updated = client.patch(
        f"/api/v1/documents/{ids['ready_document_id']}/classification",
        headers=admin_headers,
        json={
            "spaceId": ids["private_space_id"],
            "departmentId": ids["private_department_id"],
            "categoryId": ids["private_category_id"],
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["knowledgeSpaceId"] == ids["private_space_id"]
    assert body["categoryDepartmentId"] == ids["private_department_id"]
    assert body["knowledgeCategoryId"] == ids["private_category_id"]
    assert body["knowledgeSpace"]["name"] == "内部知识库"
    assert body["knowledgeCategory"]["code"] == "policy"

    from server.app.models.document import Document
    from server.app.models.logs import AuditLog

    with SessionLocal() as session:
        document = session.get(Document, ids["ready_document_id"])
        assert document.knowledge_space_id == ids["private_space_id"]
        assert document.category_department_id == ids["private_department_id"]
        assert document.knowledge_category_id == ids["private_category_id"]
        audit = session.scalar(
            select(AuditLog).where(
                AuditLog.resource_id == ids["ready_document_id"],
                AuditLog.action == "DOCUMENT_CLASSIFICATION_UPDATED",
            )
        )
        assert audit is not None
        assert audit.before_snapshot["knowledge_category_id"] == ids[
            "refund_category_id"
        ]
        assert audit.after_snapshot["knowledge_category_id"] == ids[
            "private_category_id"
        ]

    old_category = client.get(
        f"/api/v1/documents?categoryId={ids['refund_category_id']}&pageSize=20",
        headers=admin_headers,
    )
    assert old_category.status_code == 200
    assert old_category.json()["data"] == []

    new_category = client.get(
        f"/api/v1/documents?categoryId={ids['private_category_id']}&pageSize=20",
        headers=admin_headers,
    )
    assert new_category.status_code == 200
    assert {item["title"] for item in new_category.json()["data"]} == {
        "Refund SOP",
        "Private Playbook",
    }

    invalid = client.patch(
        f"/api/v1/documents/{ids['ready_document_id']}/classification",
        headers=admin_headers,
        json={
            "spaceId": ids["private_space_id"],
            "departmentId": ids["support_department_id"],
            "categoryId": ids["private_category_id"],
        },
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "CLASSIFICATION_PATH_INVALID"


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


def test_retry_failed_import_job_routes_chunking_and_indexing_to_their_workers(
    monkeypatch,
):
    client, SessionLocal = build_test_client()
    admin_headers = login_admin(client)
    ids = seed_document_center_data(SessionLocal)
    queued_parse: list[str] = []
    queued_embedding: list[str] = []

    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob, ImportJobStatus
    from server.app.services import import_service

    with SessionLocal() as session:
        job = session.get(ImportJob, ids["failed_job_id"])
        document = session.get(Document, ids["failed_document_id"])
        assert job is not None
        assert document is not None
        job.retry_count = 0
        job.status = ImportJobStatus.FAILED.value
        job.stage = "CHUNKING"
        document.status = DocumentStatus.FAILED
        session.commit()

    monkeypatch.setattr(import_service, "enqueue_parse_task", queued_parse.append)
    chunking_retry = client.post(
        f"/api/v1/import-jobs/{ids['failed_job_id']}/retries",
        headers=admin_headers,
    )
    assert chunking_retry.status_code == 200
    assert chunking_retry.json()["stage"] == "CHUNKING"
    assert queued_parse == [ids["failed_job_id"]]

    with SessionLocal() as session:
        job = session.get(ImportJob, ids["failed_job_id"])
        document = session.get(Document, ids["failed_document_id"])
        assert job is not None
        assert document is not None
        job.status = ImportJobStatus.FAILED.value
        job.stage = "INDEXING"
        document.status = DocumentStatus.FAILED
        session.commit()

    monkeypatch.setattr(import_service, "enqueue_embedding_task", queued_embedding.append)
    indexing_retry = client.post(
        f"/api/v1/import-jobs/{ids['failed_job_id']}/retries",
        headers=admin_headers,
    )
    assert indexing_retry.status_code == 200
    assert indexing_retry.json()["stage"] == "INDEXING"
    assert queued_embedding == [ids["failed_job_id"]]


def test_document_summary_returns_visible_document_and_chunk_totals():
    client, SessionLocal = build_test_client()
    employee_headers = login_employee(client)

    from server.app.models.document import (
        Document,
        DocumentAccessRule,
        DocumentAccessSubjectType,
        DocumentStatus,
    )
    from server.app.models.user import Department, Tenant

    with SessionLocal() as session:
        tenant = session.scalar(select(Tenant))
        private_department = session.scalar(
            select(Department).where(Department.code == "PRIVATE")
        )
        other_tenant = Tenant(name="其他租户")
        session.add(other_tenant)
        session.flush()

        visible_documents = [
            Document(
                tenant_id=tenant.id,
                title="员工可见文档一",
                file_name="employee-visible-one.md",
                file_type="MARKDOWN",
                mime_type="text/markdown",
                file_size=10,
                object_key="uploads/employee-visible-one.md",
                checksum="summary-visible-one",
                status=DocumentStatus.READY,
                chunk_count=3,
            ),
            Document(
                tenant_id=tenant.id,
                title="员工可见文档二",
                file_name="employee-visible-two.md",
                file_type="MARKDOWN",
                mime_type="text/markdown",
                file_size=10,
                object_key="uploads/employee-visible-two.md",
                checksum="summary-visible-two",
                status=DocumentStatus.EMBEDDING,
                chunk_count=5,
            ),
        ]
        hidden_document = Document(
            tenant_id=tenant.id,
            title="无访问范围文档",
            file_name="summary-private.md",
            file_type="MARKDOWN",
            mime_type="text/markdown",
            file_size=10,
            object_key="uploads/summary-private.md",
            checksum="summary-private",
            status=DocumentStatus.READY,
            chunk_count=21,
        )
        deleted_document = Document(
            tenant_id=tenant.id,
            title="已删除文档",
            file_name="summary-deleted.md",
            file_type="MARKDOWN",
            mime_type="text/markdown",
            file_size=10,
            object_key="uploads/summary-deleted.md",
            checksum="summary-deleted",
            status=DocumentStatus.DELETED,
            chunk_count=99,
            deleted_at=datetime.now(UTC),
        )
        other_tenant_document = Document(
            tenant_id=other_tenant.id,
            title="其他租户文档",
            file_name="summary-other-tenant.md",
            file_type="MARKDOWN",
            mime_type="text/markdown",
            file_size=10,
            object_key="uploads/summary-other-tenant.md",
            checksum="summary-other-tenant",
            status=DocumentStatus.READY,
            chunk_count=88,
        )
        session.add_all(
            [
                *visible_documents,
                hidden_document,
                deleted_document,
                other_tenant_document,
            ]
        )
        session.flush()
        session.add_all(
            [
                *[
                    DocumentAccessRule(
                        tenant_id=tenant.id,
                        document_id=document.id,
                        subject_type=DocumentAccessSubjectType.ALL_AUTHENTICATED,
                    )
                    for document in visible_documents
                ],
                DocumentAccessRule(
                    tenant_id=tenant.id,
                    document_id=hidden_document.id,
                    subject_type=DocumentAccessSubjectType.DEPARTMENT,
                    subject_id=private_department.id,
                ),
                DocumentAccessRule(
                    tenant_id=tenant.id,
                    document_id=deleted_document.id,
                    subject_type=DocumentAccessSubjectType.ALL_AUTHENTICATED,
                ),
                DocumentAccessRule(
                    tenant_id=other_tenant.id,
                    document_id=other_tenant_document.id,
                    subject_type=DocumentAccessSubjectType.ALL_AUTHENTICATED,
                ),
            ]
        )
        session.commit()

    response = client.get("/api/v1/documents/summary", headers=employee_headers)

    assert response.status_code == 200
    assert response.json() == {
        "syncedDocumentCount": 2,
        "totalChunkCount": 8,
    }
