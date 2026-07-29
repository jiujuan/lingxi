from sqlalchemy import select

from server.tests.test_auth_rbac import build_test_client
from server.tests.test_chat_sse import _seed_chat_data
from server.tests.test_knowledge_documents_api import login_employee
from server.tests.test_model_config import login_admin


def _create_answer_with_citation(client, headers, retrieval_scope=None):
    session_id = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]
    payload = {"content": "退款需要谁审批？"}
    if retrieval_scope is not None:
        payload["retrievalScope"] = retrieval_scope
    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/message-runs",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 200
    run_id = response.text.split('"runId": "')[1].split('"')[0]
    citation_id = response.text.split('"citationId": "')[1].split('"')[0]
    return run_id, citation_id


def test_query_run_citations_source_and_explanation_are_authorized():
    client, SessionLocal = build_test_client()
    _seed_chat_data(SessionLocal)
    employee_headers = login_employee(client)
    run_id, citation_id = _create_answer_with_citation(client, employee_headers)

    detail = client.get(f"/api/v1/query-runs/{run_id}", headers=employee_headers)
    assert detail.status_code == 200
    assert detail.json()["runId"] == run_id
    assert detail.json()["status"] == "COMPLETED"

    citations = client.get(f"/api/v1/query-runs/{run_id}/citations", headers=employee_headers)
    assert citations.status_code == 200
    assert citations.json()["data"][0]["id"] == citation_id
    assert citations.json()["data"][0]["title"] == "Refund SOP"
    assert citations.json()["data"][0]["rank"] == 1
    assert citations.json()["data"][0]["score"] > 0

    source = client.get(f"/api/v1/citations/{citation_id}/source", headers=employee_headers)
    assert source.status_code == 200
    assert source.json()["documentTitle"] == "Refund SOP"
    assert source.json()["quote"] == "退款需要主管审批。"

    explanation = client.get(
        f"/api/v1/query-runs/{run_id}/retrieval-explanation",
        headers=employee_headers,
    )
    assert explanation.status_code == 200
    body = explanation.json()
    assert body["runId"] == run_id
    assert body["stages"]["vector"]
    assert body["stages"]["text"]
    assert body["stages"]["rrf"]
    assert body["stages"]["rerank"]


def test_scoped_query_run_explanation_and_citations_include_classification_path():
    from server.app.models.user import Department

    client, SessionLocal = build_test_client()
    _seed_chat_data(SessionLocal)
    employee_headers = login_employee(client)
    with SessionLocal() as session:
        support_department = session.scalar(
            select(Department).where(Department.code == "SUPPORT")
        )
        assert support_department is not None
        support_department_id = support_department.id
        support_department_name = support_department.name

    run_id, citation_id = _create_answer_with_citation(
        client,
        employee_headers,
        {
            "spaceId": "space-support",
            "classificationDepartmentId": support_department_id,
            "categoryId": "cat-refund",
        },
    )
    expected_path = f"客服知识库 / {support_department_name} / 退款专题"

    detail = client.get(f"/api/v1/query-runs/{run_id}", headers=employee_headers)
    assert detail.status_code == 200
    detail_scope = detail.json()["retrievalScope"]
    assert detail_scope["spaceId"] == "space-support"
    assert detail_scope["spaceName"] == "客服知识库"
    assert detail_scope["classificationDepartmentId"] == support_department_id
    assert detail_scope["classificationDepartmentName"] == support_department_name
    assert detail_scope["categoryId"] == "cat-refund"
    assert detail_scope["categoryName"] == "退款专题"
    assert detail_scope["displayPath"] == expected_path

    explanation = client.get(
        f"/api/v1/query-runs/{run_id}/retrieval-explanation",
        headers=employee_headers,
    )
    assert explanation.status_code == 200
    explanation_body = explanation.json()
    assert explanation_body["retrievalScope"]["displayPath"] == expected_path
    assert explanation_body["filters"]["scopeSpaceId"] == "space-support"
    assert (
        explanation_body["filters"]["scopeClassificationDepartmentId"]
        == support_department_id
    )
    assert explanation_body["filters"]["scopeCategoryId"] == "cat-refund"

    citations = client.get(f"/api/v1/query-runs/{run_id}/citations", headers=employee_headers)
    assert citations.status_code == 200
    citation = citations.json()["data"][0]
    assert citation["id"] == citation_id
    assert citation["documentId"]
    assert citation["qaPairId"]
    assert citation["classification"]["displayPath"] == expected_path

    source = client.get(f"/api/v1/citations/{citation_id}/source", headers=employee_headers)
    assert source.status_code == 200
    assert source.json()["classification"]["displayPath"] == expected_path


def test_unclassified_citation_displays_unclassified_without_breaking_legacy_fields():
    from server.app.models.chat import QueryCitation, QueryRun
    from server.app.models.document import (
        Document,
        DocumentAccessRule,
        DocumentAccessSubjectType,
        DocumentStatus,
    )
    from server.app.models.user import Tenant

    client, SessionLocal = build_test_client()
    _seed_chat_data(SessionLocal)
    employee_headers = login_employee(client)
    session_id = client.post("/api/v1/chat/sessions", headers=employee_headers, json={}).json()[
        "id"
    ]

    with SessionLocal() as session:
        tenant = session.scalar(select(Tenant))
        assert tenant is not None
        document = Document(
            tenant_id=tenant.id,
            title="Legacy Unclassified",
            file_name="legacy.md",
            file_type="MARKDOWN",
            mime_type="text/markdown",
            file_size=20,
            object_key="documents/legacy.md",
            checksum="legacy-unclassified",
            status=DocumentStatus.READY,
        )
        session.add(document)
        session.flush()
        session.add(
            DocumentAccessRule(
                tenant_id=tenant.id,
                document_id=document.id,
                subject_type=DocumentAccessSubjectType.ALL_AUTHENTICATED,
                subject_id=None,
            )
        )
        run = QueryRun(
            tenant_id=tenant.id,
            run_id="run-unclassified",
            session_id=session_id,
            user_message_id=None,
            question="历史未分类文档",
            status="COMPLETED",
            retrieval_snapshot={},
            token_usage={},
            request_id="req-unclassified",
        )
        session.add(run)
        session.flush()
        citation = QueryCitation(
            tenant_id=tenant.id,
            run_id=run.id,
            message_id=None,
            document_id=document.id,
            qa_pair_id=None,
            quote="历史未分类引用。",
            rank=1,
            snapshot={"title": document.title, "score": 0.8},
        )
        session.add(citation)
        session.commit()
        citation_id = citation.id

    citations = client.get(
        "/api/v1/query-runs/run-unclassified/citations", headers=employee_headers
    )
    assert citations.status_code == 200
    body = citations.json()["data"][0]
    assert body["id"] == citation_id
    assert body["documentId"]
    assert body["qaPairId"] is None
    assert body["classification"]["spaceId"] is None
    assert body["classification"]["displayPath"] == "未分类"

    source = client.get(f"/api/v1/citations/{citation_id}/source", headers=employee_headers)
    assert source.status_code == 200
    assert source.json()["classification"]["displayPath"] == "未分类"


def test_citation_source_requires_current_document_permission_but_deleted_snapshot_survives():
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.document import DocumentAccessRule
    from server.app.models.chat import QueryCitation

    client, SessionLocal = build_test_client()
    _seed_chat_data(SessionLocal)
    employee_headers = login_employee(client)
    admin_headers = login_admin(client)
    _run_id, citation_id = _create_answer_with_citation(client, employee_headers)

    with SessionLocal() as session:
        citation = session.get(QueryCitation, citation_id)
        rules = session.scalars(
            select(DocumentAccessRule).where(
                DocumentAccessRule.document_id == citation.document_id
            )
        ).all()
        for rule in rules:
            session.delete(rule)
        session.commit()

    forbidden = client.get(f"/api/v1/citations/{citation_id}/source", headers=employee_headers)
    assert forbidden.status_code == 403

    with SessionLocal() as session:
        citation = session.get(QueryCitation, citation_id)
        document = session.get(Document, citation.document_id)
        document.status = DocumentStatus.DELETED
        session.commit()

    source = client.get(f"/api/v1/citations/{citation_id}/source", headers=admin_headers)
    assert source.status_code == 200
    assert source.json()["documentDeleted"] is True
    assert source.json()["quote"] == "退款需要主管审批。"
