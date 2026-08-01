from dataclasses import replace

import pytest
from sqlalchemy import select

from server.tests.test_document_permissions import build_session


def _seed_retrieval_dataset(session, identity):
    from server.app.models.document import (
        Document,
        DocumentAccessRule,
        DocumentAccessSubjectType,
        DocumentStatus,
    )
    from server.app.models.knowledge_category import KnowledgeCategory, KnowledgeSpace
    from server.app.models.qa_pair import QaPair

    tenant_id = identity["tenant"].id
    support = identity["departments"]["support"]
    private = identity["departments"]["private"]

    support_space = KnowledgeSpace(
        id="space-support",
        tenant_id=tenant_id,
        name="客服知识库",
        code="support-kb",
    )
    refund_category = KnowledgeCategory(
        id="cat-refund",
        tenant_id=tenant_id,
        space_id=support_space.id,
        department_id=support.id,
        name="退款专题",
        code="refund",
    )
    invoice_category = KnowledgeCategory(
        id="cat-invoice",
        tenant_id=tenant_id,
        space_id=support_space.id,
        department_id=support.id,
        name="发票专题",
        code="invoice",
    )
    session.add_all([support_space, refund_category, invoice_category])
    session.flush()

    refund_doc = Document(
        tenant_id=tenant_id,
        title="Refund SOP",
        file_name="refund.md",
        file_type="MARKDOWN",
        mime_type="text/markdown",
        file_size=100,
        object_key="documents/refund.md",
        checksum="refund",
        status=DocumentStatus.READY,
        knowledge_space_id="space-support",
        category_department_id=support.id,
        knowledge_category_id="cat-refund",
    )
    invoice_doc = Document(
        tenant_id=tenant_id,
        title="Invoice SOP",
        file_name="invoice.md",
        file_type="MARKDOWN",
        mime_type="text/markdown",
        file_size=100,
        object_key="documents/invoice.md",
        checksum="invoice",
        status=DocumentStatus.READY,
        knowledge_space_id="space-support",
        category_department_id=support.id,
        knowledge_category_id="cat-invoice",
    )
    private_doc = Document(
        tenant_id=tenant_id,
        title="Private Payroll",
        file_name="payroll.md",
        file_type="MARKDOWN",
        mime_type="text/markdown",
        file_size=100,
        object_key="documents/payroll.md",
        checksum="payroll",
        status=DocumentStatus.READY,
        knowledge_space_id="space-support",
        category_department_id=support.id,
        knowledge_category_id="cat-refund",
    )
    session.add_all([refund_doc, invoice_doc, private_doc])
    session.flush()

    pairs = [
        QaPair(
            tenant_id=tenant_id,
            document_id=refund_doc.id,
            pair_index=0,
            question="退款需要谁审批？",
            answer="退款需要主管审批。",
            quote="退款需要主管审批。",
            page_no=1,
            question_embedding=[1.0, 0.0, 0.0, 0.0],
            search_text="退款 需要 主管 审批",
            status="ACTIVE",
        ),
        QaPair(
            tenant_id=tenant_id,
            document_id=invoice_doc.id,
            pair_index=1,
            question="已开票订单退款前要做什么？",
            answer="已开票订单退款前需要先红冲发票。",
            quote="已开票订单需先红冲发票。",
            page_no=2,
            question_embedding=[0.8, 0.2, 0.0, 0.0],
            search_text="已 开票 订单 退款 前 红冲 发票",
            status="ACTIVE",
        ),
        QaPair(
            tenant_id=tenant_id,
            document_id=private_doc.id,
            pair_index=0,
            question="工资表在哪里？",
            answer="工资表在财务私有目录。",
            quote="工资表在财务私有目录。",
            page_no=1,
            question_embedding=[1.0, 0.0, 0.0, 0.0],
            search_text="工资 表 财务 私有",
            status="ACTIVE",
        ),
    ]
    session.add_all(pairs)
    session.add_all(
        [
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=refund_doc.id,
                subject_type=DocumentAccessSubjectType.ALL_AUTHENTICATED,
                subject_id=None,
            ),
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=invoice_doc.id,
                subject_type=DocumentAccessSubjectType.DEPARTMENT,
                subject_id=support.id,
            ),
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=private_doc.id,
                subject_type=DocumentAccessSubjectType.DEPARTMENT,
                subject_id=private.id,
            ),
        ]
    )
    session.commit()
    return {"refund_doc": refund_doc.id, "invoice_doc": invoice_doc.id, "private_doc": private_doc.id}


def _employee_context(identity):
    from server.app.core.permissions import AccessContext

    return AccessContext(
        tenant_id=identity["tenant"].id,
        user_id=identity["users"]["employee"].id,
        department_id=identity["departments"]["support"].id,
        role_ids=[identity["roles"]["employee"].id],
        permissions={"DOCUMENT_READ", "CHAT_READ", "CHAT_WRITE"},
        role_codes={"EMPLOYEE"},
    )


def _seed_hybrid_evidence(session, identity):
    from server.app.models.qa_pair import DocumentChunk, QaPair

    ids = _seed_retrieval_dataset(session, identity)
    qa_pairs = list(
        session.scalars(
            select(QaPair)
            .where(QaPair.document_id.in_([ids["refund_doc"], ids["invoice_doc"]]))
            .order_by(QaPair.pair_index)
        )
    )
    chunks = [
        DocumentChunk(
            tenant_id=identity["tenant"].id,
            document_id=ids["refund_doc"],
            chunk_index=0,
            title_path=["退款", "审批"],
            content="退款需要主管审批，审批后才能执行退款。",
            page_start=1,
            page_end=1,
            source_locator={
                "block": 1,
                "_lingxi_chunk_span": {
                    "merged_char_start": 0,
                    "merged_char_end": 20,
                },
            },
            source_locators=[
                {
                    "block": 1,
                    "_lingxi_chunk_span": {
                        "merged_char_start": 0,
                        "merged_char_end": 20,
                    },
                }
            ],
            content_hash="a" * 64,
            embedding=[1.0, 0.0, 0.0, 0.0],
            search_text="退款 审批 主管",
            status="ACTIVE",
            chunk_level="CHILD",
        ),
        DocumentChunk(
            tenant_id=identity["tenant"].id,
            document_id=ids["invoice_doc"],
            chunk_index=1,
            title_path=["发票", "退款"],
            content="已开票订单退款前需要先红冲发票。",
            page_start=2,
            page_end=2,
            source_locator={
                "block": 2,
                "_lingxi_chunk_span": {
                    "merged_char_start": 30,
                    "merged_char_end": 50,
                },
            },
            source_locators=[
                {
                    "block": 2,
                    "_lingxi_chunk_span": {
                        "merged_char_start": 30,
                        "merged_char_end": 50,
                    },
                }
            ],
            content_hash="b" * 64,
            embedding=[0.8, 0.2, 0.0, 0.0],
            search_text="已 开票 订单 退款 红冲 发票",
            status="ACTIVE",
            chunk_level="CHILD",
        ),
    ]
    session.add_all(chunks)
    session.flush()
    qa_pairs[0].chunk_id = chunks[0].id
    qa_pairs[1].chunk_id = chunks[1].id
    session.commit()
    return qa_pairs, chunks


def _hybrid_service(session, *, rrf_k=10, weights=None):
    from server.app.core.retrieval_config import get_retrieval_config
    from server.app.services.retrieval_service import RetrievalService

    return RetrievalService(
        session,
        config=replace(get_retrieval_config(), rrf_k=rrf_k),
        hybrid_chunk_retrieval_enabled=True,
        rrf_channel_weights=weights,
    )


def _stub_hybrid_channels(monkeypatch, service, *, qa_vector, qa_text, chunk_vector, chunk_text):
    monkeypatch.setattr(service, "_embed_query", lambda _tenant_id, _question: [1.0, 0.0, 0.0, 0.0])
    monkeypatch.setattr(service.tokenizer, "tokenize", lambda _question: ["退款"])
    monkeypatch.setattr(service.repo, "search_qa_vector", lambda *_args: qa_vector)
    monkeypatch.setattr(service.repo, "search_qa_text", lambda *_args: qa_text)
    monkeypatch.setattr(service.repo, "search_chunk_vector", lambda *_args: chunk_vector)
    monkeypatch.setattr(service.repo, "search_chunk_text", lambda *_args: chunk_text)


def test_hybrid_retrieval_fuses_four_channels_into_one_source_chunk_and_snapshots_ranks(monkeypatch):
    session, identity = build_session()
    qa_pairs, chunks = _seed_hybrid_evidence(session, identity)
    chunks[0].chunker_config_hash = "chunk-config-b"
    chunks[1].chunker_config_hash = "chunk-config-a"
    session.flush()
    service = _hybrid_service(
        session,
        weights={
            "qa_vector": 2.0,
            "qa_text": 1.0,
            "chunk_vector": 3.0,
            "chunk_text": 4.0,
        },
    )
    _stub_hybrid_channels(
        monkeypatch,
        service,
        qa_vector=[(qa_pairs[0], 0.91)],
        qa_text=[(qa_pairs[0], 0.81), (qa_pairs[1], 0.50)],
        chunk_vector=[(chunks[0], 0.71)],
        chunk_text=[(chunks[0], 0.61), (chunks[1], 0.40)],
    )

    result = service.retrieve(_employee_context(identity), "退款需要谁审批？")

    assert len(result.candidates) == 2
    first = result.candidates[0]
    assert first.qa_pair_id == qa_pairs[0].id
    assert first.chunk_id == chunks[0].id
    assert first.answer == chunks[0].content
    assert first.rrf_score == pytest.approx(10 / 11)
    assert first.channel_scores == {
        "qa_vector": 0.91,
        "qa_text": 0.81,
        "chunk_vector": 0.71,
        "chunk_text": 0.61,
    }
    assert first.channel_ranks == {
        "qa_vector": 1,
        "qa_text": 1,
        "chunk_vector": 1,
        "chunk_text": 1,
    }
    assert result.snapshot["stages"]["vector"]
    assert result.snapshot["stages"]["text"]
    assert result.snapshot["stages"]["qaVector"][0]["rank"] == 1
    assert result.snapshot["stages"]["chunkVector"][0]["chunkId"] == chunks[0].id
    assert result.snapshot["rrfParameters"] == {
        "k": 10,
        "weights": {
            "qa_vector": 2.0,
            "qa_text": 1.0,
            "chunk_vector": 3.0,
            "chunk_text": 4.0,
        },
    }
    assert result.snapshot["chunkerConfigHashes"] == ["chunk-config-a", "chunk-config-b"]
    assert len(result.snapshot["retrievalConfigHash"]) == 64
    fused_snapshot = result.snapshot["stages"]["rrf"][0]
    assert fused_snapshot["evidenceId"] == chunks[0].id
    assert fused_snapshot["channelRanks"] == first.channel_ranks
    assert fused_snapshot["channelScores"] == first.channel_scores


def test_hybrid_retrieval_deduplicates_by_source_span_then_content_hash_then_overlap():
    from server.app.schemas.retrieval import RetrievalEvidence

    session, _identity = build_session()
    service = _hybrid_service(session)
    common = dict(
        evidence_type="CHUNK",
        document_id="document-1",
        parent_chunk_id=None,
        quote=None,
        title_path=("Section",),
        page_start=1,
        page_end=1,
    )
    source_span = RetrievalEvidence(
        evidence_id="span-winner",
        chunk_id="chunk-span-winner",
        content="source span winner",
        source_locator={"block": 1, "_lingxi_chunk_span": {"merged_char_start": 0, "merged_char_end": 100}},
        content_hash="hash-span-winner",
        channel_scores={"chunk_vector": 0.8},
        channel_ranks={"chunk_vector": 1},
        fused_score=0.8,
        **common,
    )
    same_span = RetrievalEvidence(
        evidence_id="same-span",
        chunk_id="chunk-same-span",
        content="different content but same locator",
        source_locator={"block": 1, "_lingxi_chunk_span": {"merged_char_start": 0, "merged_char_end": 100}},
        content_hash="hash-other",
        channel_scores={"chunk_text": 0.7},
        channel_ranks={"chunk_text": 1},
        fused_score=0.7,
        **common,
    )
    same_hash = RetrievalEvidence(
        evidence_id="same-hash",
        chunk_id="chunk-same-hash",
        content="same hash but different span",
        source_locator={"block": 2, "_lingxi_chunk_span": {"merged_char_start": 200, "merged_char_end": 300}},
        content_hash="hash-span-winner",
        channel_scores={"qa_vector": 0.6},
        channel_ranks={"qa_vector": 1},
        fused_score=0.6,
        **common,
    )
    overlap = RetrievalEvidence(
        evidence_id="overlap",
        chunk_id="chunk-overlap",
        content="overlap span",
        source_locator={"block": 1, "_lingxi_chunk_span": {"merged_char_start": 10, "merged_char_end": 100}},
        content_hash="hash-overlap",
        channel_scores={"qa_text": 0.5},
        channel_ranks={"qa_text": 1},
        fused_score=0.5,
        **common,
    )

    deduplicated = service._deduplicate_evidence([source_span, same_span, same_hash, overlap])

    assert [item.evidence_id for item in deduplicated] == ["span-winner"]
    assert deduplicated[0].channel_scores == {
        "chunk_vector": 0.8,
        "chunk_text": 0.7,
        "qa_vector": 0.6,
        "qa_text": 0.5,
    }


def test_hybrid_retrieval_deduplicates_same_content_hash_across_documents_with_merged_channels():
    from server.app.schemas.retrieval import RetrievalEvidence

    session, _identity = build_session()
    service = _hybrid_service(session)
    common = dict(
        evidence_type="CHUNK",
        parent_chunk_id=None,
        quote=None,
        title_path=("Section",),
        page_start=1,
        page_end=1,
        content="shared policy text",
        content_hash="shared-content-hash",
    )
    higher_score = RetrievalEvidence(
        evidence_id="document-one",
        document_id="document-1",
        chunk_id="chunk-one",
        source_locator={
            "block": 1,
            "_lingxi_chunk_span": {"merged_char_start": 0, "merged_char_end": 100},
        },
        channel_scores={"qa_vector": 0.9},
        channel_ranks={"qa_vector": 1},
        fused_score=0.9,
        **common,
    )
    lower_score = RetrievalEvidence(
        evidence_id="document-two",
        document_id="document-2",
        chunk_id="chunk-two",
        source_locator={
            "block": 2,
            "_lingxi_chunk_span": {"merged_char_start": 200, "merged_char_end": 300},
        },
        channel_scores={"chunk_text": 0.8},
        channel_ranks={"chunk_text": 1},
        fused_score=0.8,
        **common,
    )

    deduplicated = service._deduplicate_evidence([lower_score, higher_score])

    assert [item.evidence_id for item in deduplicated] == ["document-one"]
    assert deduplicated[0].fused_score == 0.9
    assert deduplicated[0].channel_scores == {"qa_vector": 0.9, "chunk_text": 0.8}
    assert deduplicated[0].channel_ranks == {"qa_vector": 1, "chunk_text": 1}


def test_hybrid_content_hash_duplicate_keeps_highest_score_chunk_identity_and_merges_channels():
    from server.app.schemas.retrieval import RetrievalEvidence

    session, _identity = build_session()
    service = _hybrid_service(session)
    qa_loser = RetrievalEvidence(
        evidence_type="QA",
        evidence_id="qa-source-chunk",
        document_id="document-qa",
        chunk_id="chunk-qa",
        parent_chunk_id="parent-qa",
        content="low score QA source content",
        quote="low score QA quote",
        title_path=("QA title",),
        page_start=2,
        page_end=3,
        source_locator={"block": "qa", "offset": 20},
        content_hash="same-hash-across-documents",
        qa_pair_id="qa-pair-low",
        question="low score question",
        answer="low score answer",
        pair_index=7,
        channel_scores={"qa_vector": 0.4},
        channel_ranks={"qa_vector": 1},
        fused_score=0.4,
    )
    chunk_winner = RetrievalEvidence(
        evidence_type="CHUNK",
        evidence_id="chunk-source",
        document_id="document-chunk",
        chunk_id="chunk-high",
        parent_chunk_id="parent-chunk",
        content="high score Chunk source content",
        quote="high score Chunk quote",
        title_path=("Chunk title",),
        page_start=8,
        page_end=9,
        source_locator={"block": "chunk", "offset": 80},
        content_hash="same-hash-across-documents",
        qa_pair_id=None,
        question=None,
        answer=None,
        pair_index=2,
        channel_scores={"chunk_text": 0.9},
        channel_ranks={"chunk_text": 1},
        fused_score=0.9,
    )

    deduplicated = service._deduplicate_evidence([qa_loser, chunk_winner])

    assert len(deduplicated) == 1
    evidence = deduplicated[0]
    assert evidence.evidence_type == "CHUNK"
    assert evidence.evidence_id == chunk_winner.evidence_id
    assert evidence.document_id == chunk_winner.document_id
    assert evidence.chunk_id == chunk_winner.chunk_id
    assert evidence.content == chunk_winner.content
    assert evidence.source_locator == chunk_winner.source_locator
    assert evidence.quote == chunk_winner.quote
    assert (evidence.page_start, evidence.page_end) == (8, 9)
    assert evidence.parent_chunk_id == chunk_winner.parent_chunk_id
    assert evidence.qa_pair_id is None
    assert evidence.channel_scores == {"qa_vector": 0.4, "chunk_text": 0.9}
    assert evidence.channel_ranks == {"qa_vector": 1, "chunk_text": 1}


def test_retrieval_evidence_legacy_candidate_adapter_preserves_qa_raw_scores():
    from server.app.schemas.retrieval import RetrievalEvidence

    candidate = RetrievalEvidence(
        evidence_type="QA",
        evidence_id="chunk-1",
        document_id="document-1",
        chunk_id="chunk-1",
        parent_chunk_id=None,
        content="source content",
        quote="source quote",
        title_path=("Refund",),
        page_start=1,
        page_end=1,
        source_locator={},
        channel_scores={"qa_vector": 0.73, "qa_text": 0.42, "chunk_text": 0.2},
        channel_ranks={"qa_vector": 1, "qa_text": 2, "chunk_text": 1},
        fused_score=0.31,
        qa_pair_id="qa-1",
        question="退款如何审批？",
        answer="主管审批",
    ).to_candidate()

    assert candidate.vector_score == 0.73
    assert candidate.text_score == 0.42
    assert candidate.to_snapshot()["vectorScore"] == 0.73
    assert candidate.to_snapshot()["textScore"] == 0.42


@pytest.mark.parametrize(
    "weights",
    [
        {"qa_vector": float("nan")},
        {"qa_text": float("inf")},
        {"chunk_vector": float("-inf")},
        {"chunk_text": -0.01},
        {"unknown": 1.0},
    ],
)
def test_hybrid_rejects_invalid_rrf_channel_weights(weights):
    session, _identity = build_session()

    with pytest.raises(ValueError):
        _hybrid_service(session, weights=weights)


def test_hybrid_accepts_zero_and_finite_rrf_channel_weights():
    session, _identity = build_session()

    service = _hybrid_service(
        session,
        weights={"qa_vector": 0, "qa_text": 0.25, "chunk_vector": 4.0, "chunk_text": 0.0},
    )

    assert service.rrf_channel_weights == {
        "qa_vector": 0.0,
        "qa_text": 0.25,
        "chunk_vector": 4.0,
        "chunk_text": 0.0,
    }


def test_hybrid_excludes_qa_with_an_invalid_source_chunk_mapping(monkeypatch):
    session, identity = build_session()
    qa_pairs, _chunks = _seed_hybrid_evidence(session, identity)
    qa_pairs[0].chunk_id = "missing-child-chunk"
    session.commit()
    service = _hybrid_service(session)
    _stub_hybrid_channels(
        monkeypatch,
        service,
        qa_vector=[(qa_pairs[0], 0.9)],
        qa_text=[(qa_pairs[0], 0.8)],
        chunk_vector=[],
        chunk_text=[],
    )

    result = service.retrieve(_employee_context(identity), "退款需要谁审批？")

    assert result.candidates == []
    assert result.snapshot["stages"]["qaVector"][0]["qaPairId"] == qa_pairs[0].id
    assert result.snapshot["stages"]["rrf"] == []


def test_hybrid_qa_source_mapping_bulk_loads_without_session_get(monkeypatch):
    session, identity = build_session()
    qa_pairs, _chunks = _seed_hybrid_evidence(session, identity)
    service = _hybrid_service(session)
    _stub_hybrid_channels(
        monkeypatch,
        service,
        qa_vector=[(qa_pairs[0], 0.9), (qa_pairs[1], 0.8)],
        qa_text=[],
        chunk_vector=[],
        chunk_text=[],
    )
    monkeypatch.setattr(
        session,
        "get",
        lambda *_args, **_kwargs: pytest.fail("QA source mapping must bulk-load Child Chunks"),
    )

    result = service.retrieve(_employee_context(identity), "退款需要谁审批？")

    assert {candidate.qa_pair_id for candidate in result.candidates} == {
        qa_pairs[0].id,
        qa_pairs[1].id,
    }


@pytest.mark.parametrize(
    "invalid_mapping",
    [
        "inactive_child",
        "wrong_child_level",
        "wrong_child_tenant",
        "wrong_child_document",
        "missing_parent",
        "inactive_parent",
        "wrong_parent_level",
        "wrong_parent_tenant",
        "wrong_parent_document",
    ],
)
def test_hybrid_excludes_qa_source_mapping_when_child_or_parent_is_invalid(
    monkeypatch, invalid_mapping
):
    from server.app.models.qa_pair import DocumentChunk

    session, identity = build_session()
    qa_pairs, chunks = _seed_hybrid_evidence(session, identity)
    qa_pair = qa_pairs[0]
    child = chunks[0]
    parent = DocumentChunk(
        tenant_id=identity["tenant"].id,
        document_id=qa_pair.document_id,
        chunk_index=99,
        title_path=["退款"],
        content="退款父分块",
        status="ACTIVE",
        chunk_level="PARENT",
    )
    session.add(parent)
    session.flush()
    child.parent_chunk_id = parent.id

    if invalid_mapping == "inactive_child":
        child.status = "DELETED"
    elif invalid_mapping == "wrong_child_level":
        child.chunk_level = "PARENT"
    elif invalid_mapping == "wrong_child_tenant":
        child.tenant_id = "other-tenant"
    elif invalid_mapping == "wrong_child_document":
        child.document_id = qa_pairs[1].document_id
    elif invalid_mapping == "missing_parent":
        child.parent_chunk_id = "missing-parent"
    elif invalid_mapping == "inactive_parent":
        parent.status = "DELETED"
    elif invalid_mapping == "wrong_parent_level":
        parent.chunk_level = "CHILD"
    elif invalid_mapping == "wrong_parent_tenant":
        parent.tenant_id = "other-tenant"
    elif invalid_mapping == "wrong_parent_document":
        parent.document_id = qa_pairs[1].document_id
    else:
        raise AssertionError(f"Unhandled invalid mapping: {invalid_mapping}")
    session.commit()

    service = _hybrid_service(session)
    _stub_hybrid_channels(
        monkeypatch,
        service,
        qa_vector=[(qa_pair, 0.9)],
        qa_text=[],
        chunk_vector=[],
        chunk_text=[],
    )

    result = service.retrieve(_employee_context(identity), "退款需要谁审批？")

    assert result.candidates == []


def test_hybrid_degrades_to_qa_only_when_chunk_text_channel_is_unavailable(monkeypatch):
    session, identity = build_session()
    qa_pairs, _chunks = _seed_hybrid_evidence(session, identity)
    service = _hybrid_service(session)
    _stub_hybrid_channels(
        monkeypatch,
        service,
        qa_vector=[(qa_pairs[0], 0.9)],
        qa_text=[(qa_pairs[0], 0.8)],
        chunk_vector=[],
        chunk_text=[],
    )
    from server.app.services.retrieval_service import ChunkChannelUnavailableError

    monkeypatch.setattr(
        service.repo,
        "search_chunk_text",
        lambda *_args: (_ for _ in ()).throw(
            ChunkChannelUnavailableError("chunk full-text index unavailable")
        ),
    )

    result = service.retrieve(_employee_context(identity), "退款需要谁审批？")

    assert result.snapshot["chunkRetrievalDegraded"] is True
    assert [candidate.qa_pair_id for candidate in result.candidates] == [qa_pairs[0].id]


def test_hybrid_disabled_uses_legacy_qa_only_paths(monkeypatch):
    session, identity = build_session()
    qa_pairs, _chunks = _seed_hybrid_evidence(session, identity)

    from server.app.services.retrieval_service import RetrievalService

    service = RetrievalService(session)
    monkeypatch.setattr(service, "_embed_query", lambda _tenant_id, _question: [1.0, 0.0, 0.0, 0.0])
    monkeypatch.setattr(service.tokenizer, "tokenize", lambda _question: ["退款"])
    monkeypatch.setattr(service.repo, "vector_search", lambda *_args: [(qa_pairs[0], 0.9)])
    monkeypatch.setattr(service.repo, "text_search", lambda *_args: [(qa_pairs[0], 0.8)])
    monkeypatch.setattr(
        service.repo,
        "search_chunk_vector",
        lambda *_args: pytest.fail("hybrid-disabled retrieval must not query chunks"),
    )

    result = service.retrieve(_employee_context(identity), "退款需要谁审批？")

    assert result.candidates[0].qa_pair_id == qa_pairs[0].id
    assert "qaVector" not in result.snapshot["stages"]
    assert result.snapshot["channels"] == ["qa_vector", "qa_text"]
    assert result.snapshot["rrfParameters"] == {
        "k": service.config.rrf_k,
        "weights": {"qa_vector": 1.0, "qa_text": 1.0},
    }
    assert result.snapshot["stages"]["vector"][0]["rank"] == 1
    assert result.snapshot["stages"]["text"][0]["rank"] == 1
    assert result.snapshot["stages"]["rrf"][0]["qaPairId"] == qa_pairs[0].id
    assert result.snapshot["stages"]["rrf"][0]["evidenceId"] == qa_pairs[0].id
    assert result.snapshot["stages"]["rrf"][0]["rrfScore"] > 0
    assert result.snapshot["stages"]["rrf"][0]["fusedScore"] > 0
    assert result.snapshot["stages"]["rrf"][0]["channelRanks"] == {
        "qa_vector": 1,
        "qa_text": 1,
    }
    assert result.snapshot["chunkerConfigHashes"] == [_chunks[0].chunker_config_hash]
    assert len(result.snapshot["retrievalConfigHash"]) == 64
    assert result.candidates[0].evidence_id is None


def test_legacy_rrf_snapshot_records_actual_rank_per_qa_channel(monkeypatch):
    session, identity = build_session()
    qa_pairs, _chunks = _seed_hybrid_evidence(session, identity)

    from server.app.services.retrieval_service import RetrievalService

    service = RetrievalService(session)
    monkeypatch.setattr(
        service,
        "_embed_query",
        lambda _tenant_id, _question: [1.0, 0.0, 0.0, 0.0],
    )
    monkeypatch.setattr(service.tokenizer, "tokenize", lambda _question: ["退款"])
    monkeypatch.setattr(
        service.repo,
        "vector_search",
        lambda *_args: [(qa_pairs[0], 0.9), (qa_pairs[1], 0.8)],
    )
    monkeypatch.setattr(
        service.repo,
        "text_search",
        lambda *_args: [(qa_pairs[1], 0.7), (qa_pairs[0], 0.6)],
    )

    result = service.retrieve(_employee_context(identity), "退款需要谁审批？")

    rrf_by_pair_id = {
        snapshot["qaPairId"]: snapshot for snapshot in result.snapshot["stages"]["rrf"]
    }
    assert rrf_by_pair_id[qa_pairs[0].id]["channelRanks"] == {
        "qa_vector": 1,
        "qa_text": 2,
    }
    assert rrf_by_pair_id[qa_pairs[1].id]["channelRanks"] == {
        "qa_vector": 2,
        "qa_text": 1,
    }
    for snapshot in rrf_by_pair_id.values():
        assert snapshot["fusedScore"] == snapshot["rrfScore"]
    assert all(candidate.evidence_id is None for candidate in result.candidates)


@pytest.mark.parametrize(
    ("chunk_error", "should_degrade"),
    [
        (None, True),
        (PermissionError("ACL failure"), False),
        (ValueError("invalid chunk configuration"), False),
    ],
)
def test_hybrid_only_degrades_for_declared_chunk_unavailability(monkeypatch, chunk_error, should_degrade):
    session, identity = build_session()
    qa_pairs, _chunks = _seed_hybrid_evidence(session, identity)
    service = _hybrid_service(session)
    monkeypatch.setattr(service, "_embed_query", lambda _tenant_id, _question: [1.0, 0.0, 0.0, 0.0])
    monkeypatch.setattr(service.tokenizer, "tokenize", lambda _question: ["退款"])
    monkeypatch.setattr(service.repo, "search_qa_vector", lambda *_args: [(qa_pairs[0], 0.9)])
    monkeypatch.setattr(service.repo, "search_qa_text", lambda *_args: [(qa_pairs[0], 0.8)])

    if should_degrade:
        from server.app.services.retrieval_service import ChunkChannelUnavailableError

        chunk_error = ChunkChannelUnavailableError("chunk index unavailable")
    monkeypatch.setattr(
        service.repo,
        "search_chunk_vector",
        lambda *_args: (_ for _ in ()).throw(chunk_error),
    )

    if should_degrade:
        result = service.retrieve(_employee_context(identity), "退款需要谁审批？")
        assert result.snapshot["chunkRetrievalDegraded"] is True
        assert result.candidates[0].qa_pair_id == qa_pairs[0].id
    else:
        with pytest.raises(type(chunk_error)):
            service.retrieve(_employee_context(identity), "退款需要谁审批？")


def test_retrieval_fuses_vector_and_text_reranks_and_keeps_snapshot():
    session, identity = build_session()
    _seed_retrieval_dataset(session, identity)

    from server.app.services.retrieval_service import RetrievalService

    result = RetrievalService(session).retrieve(
        _employee_context(identity), "已开票订单退款前要做什么？"
    )

    assert result.has_answer is True
    assert result.candidates[0].question == "已开票订单退款前要做什么？"
    assert result.snapshot["stages"]["vector"]
    assert result.snapshot["stages"]["text"]
    assert result.snapshot["stages"]["rrf"]
    assert result.snapshot["stages"]["rerank"]
    assert result.snapshot["latencyMs"] >= 0


def test_retrieval_filters_unauthorized_and_api_key_scope_before_scoring():
    session, identity = build_session()
    ids = _seed_retrieval_dataset(session, identity)

    from server.app.schemas.retrieval import RetrievalAccessScope
    from server.app.services.retrieval_service import RetrievalService

    result = RetrievalService(session).retrieve(_employee_context(identity), "工资表在哪里？")

    assert {item.document_id for item in result.candidates} <= {
        ids["refund_doc"],
        ids["invoice_doc"],
    }

    scoped = RetrievalService(session).retrieve(
        _employee_context(identity),
        "已开票订单退款前要做什么？",
        access_scope=RetrievalAccessScope(document_ids={ids["refund_doc"]}),
    )

    assert scoped.candidates
    assert {item.document_id for item in scoped.candidates} == {ids["refund_doc"]}


def test_retrieval_classification_scope_filters_without_expanding_access():
    session, identity = build_session()
    ids = _seed_retrieval_dataset(session, identity)

    from server.app.schemas.retrieval import RetrievalAccessScope
    from server.app.services.retrieval_service import RetrievalService

    result = RetrievalService(session).retrieve(
        _employee_context(identity),
        "退款需要谁审批？",
        access_scope=RetrievalAccessScope(
            space_id="space-support",
            classification_department_id=identity["departments"]["support"].id,
            category_id="cat-refund",
        ),
    )

    assert result.candidates
    assert {item.document_id for item in result.candidates} == {ids["refund_doc"]}
    assert result.snapshot["filters"]["scopeSpaceId"] == "space-support"
    assert (
        result.snapshot["filters"]["scopeClassificationDepartmentId"]
        == identity["departments"]["support"].id
    )
    assert result.snapshot["filters"]["scopeCategoryId"] == "cat-refund"


def test_retrieval_classification_scope_supports_space_only():
    session, identity = build_session()
    ids = _seed_retrieval_dataset(session, identity)

    from server.app.schemas.retrieval import RetrievalAccessScope
    from server.app.services.retrieval_service import RetrievalService

    result = RetrievalService(session).retrieve(
        _employee_context(identity),
        "已开票订单退款前要做什么？",
        access_scope=RetrievalAccessScope(space_id="space-support"),
    )

    assert {item.document_id for item in result.candidates} <= {
        ids["refund_doc"],
        ids["invoice_doc"],
    }
    assert ids["private_doc"] not in {item.document_id for item in result.candidates}


def test_normalize_retrieval_scope_rejects_partial_classification_paths():
    import pytest

    from server.app.schemas.retrieval import RetrievalAccessScope
    from server.app.services.retrieval_service import normalize_retrieval_scope

    with pytest.raises(
        ValueError, match="classification_department_id requires space_id"
    ):
        normalize_retrieval_scope(
            RetrievalAccessScope(classification_department_id="dept-1")
        )

    with pytest.raises(
        ValueError,
        match="category_id requires space_id and classification_department_id",
    ):
        normalize_retrieval_scope(
            RetrievalAccessScope(space_id="space-1", category_id="cat-1")
        )


def test_snapshot_stages_are_capped_per_config():
    from dataclasses import replace

    session, identity = build_session()
    _seed_retrieval_dataset(session, identity)

    from server.app.core.retrieval_config import get_retrieval_config
    from server.app.services.retrieval_service import RetrievalService

    capped_config = replace(get_retrieval_config(), snapshot_max_items_per_stage=1)
    result = RetrievalService(session, config=capped_config).retrieve(
        _employee_context(identity), "已开票订单退款前要做什么？"
    )

    for stage in ("vector", "text", "rrf", "rerank"):
        assert len(result.snapshot["stages"][stage]) <= 1


def test_low_confidence_records_missed_question():
    session, identity = build_session()
    _seed_retrieval_dataset(session, identity)

    from server.app.models.chat import MissedQuestion
    from server.app.services.retrieval_service import RetrievalService

    result = RetrievalService(session).retrieve(
        _employee_context(identity), "火星基地报销制度是什么？"
    )

    missed = session.scalars(select(MissedQuestion)).all()
    assert result.has_answer is False
    assert missed
    assert missed[0].missed_metadata["requestId"].startswith("req_")
