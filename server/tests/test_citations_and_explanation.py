from sqlalchemy import select

from server.tests.test_auth_rbac import build_test_client
from server.tests.test_chat_sse import _seed_chat_data
from server.tests.test_knowledge_documents_api import login_employee
from server.tests.test_model_config import login_admin


def _create_answer_with_citation(client, headers):
    session_id = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]
    response = client.post(
        f"/api/v1/chat/sessions/{session_id}/message-runs",
        headers=headers,
        json={"content": "退款需要谁审批？"},
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
