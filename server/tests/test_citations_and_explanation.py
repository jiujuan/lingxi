import pytest
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


def test_chunk_citation_snapshot_resolves_the_exact_chunk_source():
    from server.app.models.chat import QueryCitation
    from server.app.models.qa_pair import DocumentChunk

    client, SessionLocal = build_test_client()
    _seed_chat_data(SessionLocal)
    employee_headers = login_employee(client)
    _run_id, citation_id = _create_answer_with_citation(client, employee_headers)

    with SessionLocal() as session:
        citation = session.get(QueryCitation, citation_id)
        assert citation is not None
        chunk = DocumentChunk(
            tenant_id=citation.tenant_id,
            document_id=citation.document_id,
            chunk_index=44,
            title_path=["退款", "审批"],
            content="纯 Chunk 引用应当返回这一段原文。",
            page_start=7,
            page_end=7,
            source_locator={"block": "refund-44", "source_rel_start": 10},
            source_locators=[{"block": "refund-44", "source_rel_start": 10}],
            status="ACTIVE",
            chunk_level="CHILD",
        )
        session.add(chunk)
        session.flush()
        citation.qa_pair_id = None
        citation.snapshot = {**citation.snapshot, "chunkId": chunk.id, "pageNo": 7}
        session.commit()

    source = client.get(f"/api/v1/citations/{citation_id}/source", headers=employee_headers)

    assert source.status_code == 200
    assert source.json()["sourceText"] == "纯 Chunk 引用应当返回这一段原文。"
    assert source.json()["sourceLocator"] == {"block": "refund-44", "source_rel_start": 10}
    assert source.json()["pageNo"] == 7


@pytest.mark.parametrize("mismatch", ["tenant", "document"])
def test_chunk_citation_snapshot_rejects_cross_tenant_or_document_source(mismatch):
    from server.app.models.chat import QueryCitation
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.qa_pair import DocumentChunk

    client, SessionLocal = build_test_client()
    _seed_chat_data(SessionLocal)
    employee_headers = login_employee(client)
    _run_id, citation_id = _create_answer_with_citation(client, employee_headers)

    with SessionLocal() as session:
        citation = session.get(QueryCitation, citation_id)
        assert citation is not None
        foreign_document_id = citation.document_id
        if mismatch == "document":
            foreign_document = Document(
                tenant_id=citation.tenant_id,
                title="Foreign source",
                file_name="foreign.md",
                file_type="MARKDOWN",
                mime_type="text/markdown",
                file_size=1,
                object_key="documents/foreign.md",
                checksum="foreign-source",
                status=DocumentStatus.READY,
            )
            session.add(foreign_document)
            session.flush()
            foreign_document_id = foreign_document.id
        foreign_chunk = DocumentChunk(
            tenant_id="foreign-tenant" if mismatch == "tenant" else citation.tenant_id,
            document_id=foreign_document_id,
            chunk_index=45,
            title_path=["Foreign"],
            content="不得泄露的跨范围来源。",
            source_locator={"block": "foreign"},
            status="ACTIVE",
            chunk_level="CHILD",
        )
        session.add(foreign_chunk)
        session.flush()
        citation.qa_pair_id = None
        citation.snapshot = {**citation.snapshot, "chunkId": foreign_chunk.id}
        session.commit()

    source = client.get(f"/api/v1/citations/{citation_id}/source", headers=employee_headers)

    assert source.status_code == 404
    assert "不得泄露" not in source.text


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


def test_prompt_keeps_child_evidence_and_citation_metadata_separate_from_hydrated_parent_context():
    from dataclasses import dataclass

    from server.app.schemas.retrieval import RetrievalCandidate
    from server.app.services.context_hydration_service import HydratedContextSegment
    from server.app.services.prompt_service import PromptService

    @dataclass(frozen=True)
    class WordCounter:
        name: str = "word-fixture"
        version: str = "1.0"

        def count(self, text: str) -> int:
            return len(text.split())

        def split_by_token_limit(self, text: str, limit: int) -> list[str]:
            words = text.split()
            return [" ".join(words[index : index + limit]) for index in range(0, len(words), limit)]

    high = RetrievalCandidate(
        qa_pair_id=None, document_id="doc", question="高分", answer="高分 Child 证据",
        quote="高分 Child 精确引用", page_no=1, pair_index=1, evidence_id="high",
        evidence_type="CHUNK", chunk_id="child-high", parent_chunk_id="parent-high",
        content="高分 Child 证据", fused_score=0.9,
    )
    low = RetrievalCandidate(
        qa_pair_id=None, document_id="doc", question="低分", answer="低分 Child 证据",
        quote="低分 Child 精确引用", page_no=2, pair_index=2, evidence_id="low",
        evidence_type="CHUNK", chunk_id="child-low", parent_chunk_id="parent-low",
        content="低分 Child 证据", fused_score=0.1,
    )
    high._lingxi_context_segments = (
        HydratedContextSegment("PARENT", "低分 Parent 补充上下文", "parent-high", "child-high"),
    )
    low._lingxi_context_segments = ()

    prompt = PromptService(token_counter=WordCounter(), context_max_tokens=200).build_chat_prompt(
        "退款怎么审批", [low, high]
    )

    assert "Evidence（用于回答）" in prompt
    assert "Citation metadata（仅引用 Child）" in prompt
    assert "Supplemental context（仅补充上下文，不单独引用）" in prompt
    assert prompt.index("高分 Child 证据") < prompt.index("低分 Child 证据") < prompt.index("低分 Parent 补充上下文")
    assert "child-high" in prompt

    bounded = PromptService(token_counter=WordCounter(), context_max_tokens=20).build_chat_prompt(
        "退款怎么审批", [low, high]
    )
    bounded_context = bounded.split("<<<REFERENCES\n", 1)[1].split("\nREFERENCES>>>", 1)[0]
    assert WordCounter().count(bounded_context) <= 20
    assert "低分 Parent 补充上下文" not in bounded_context



def test_prompt_counts_reference_separators_and_stops_when_next_high_score_evidence_would_overflow():
    from dataclasses import dataclass

    from server.app.schemas.retrieval import RetrievalCandidate
    from server.app.services.prompt_service import PromptService

    @dataclass(frozen=True)
    class SeparatorAwareCounter:
        name: str = "separator-aware"
        version: str = "1.0"

        def count(self, text: str) -> int:
            return (1 if text else 0) + text.count("\n\n") * 10

        def split_by_token_limit(self, text: str, limit: int) -> list[str]:
            return [text]

    high = RetrievalCandidate(
        qa_pair_id=None, document_id="doc", question="高分", answer="高分 evidence",
        quote="高分引用", page_no=1, pair_index=1, evidence_id="high", evidence_type="CHUNK",
        chunk_id="high", content="高分 evidence", fused_score=0.9,
    )
    low = RetrievalCandidate(
        qa_pair_id=None, document_id="doc", question="低分", answer="低分 evidence",
        quote="低分引用", page_no=1, pair_index=2, evidence_id="low", evidence_type="CHUNK",
        chunk_id="low", content="低分 evidence", fused_score=0.1,
    )

    prompt = PromptService(
        token_counter=SeparatorAwareCounter(), context_max_tokens=2
    ).build_chat_prompt("问题", [low, high])
    context = prompt.split("<<<REFERENCES\n", 1)[1].split("\nREFERENCES>>>", 1)[0]

    assert "高分 evidence" in context
    assert "低分 evidence" not in context
    assert SeparatorAwareCounter().count(context) <= 2
