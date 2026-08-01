from server.app.schemas.retrieval import RetrievalCandidate
from server.app.services.rerank_service import RerankService


def test_rerank_boosts_exact_query_and_early_position():
    candidates = [
        RetrievalCandidate(
            qa_pair_id="late",
            document_id="doc",
            question="退款流程包括哪些步骤？",
            answer="先审批后退款。",
            quote="先审批后退款。",
            page_no=2,
            pair_index=8,
            vector_score=0.9,
            text_score=0.1,
            rrf_score=0.08,
        ),
        RetrievalCandidate(
            qa_pair_id="exact",
            document_id="doc",
            question="退款需要谁审批？",
            answer="退款需要主管审批。",
            quote="退款需要主管审批。",
            page_no=1,
            pair_index=0,
            vector_score=0.7,
            text_score=0.4,
            rrf_score=0.07,
        ),
    ]

    ranked = RerankService().rerank("退款需要谁审批？", candidates)

    assert ranked[0].qa_pair_id == "exact"
    assert ranked[0].rerank_score > ranked[1].rerank_score


def test_rerank_hybrid_chunk_uses_title_path_and_content_without_changing_legacy_qa_formula():
    query = "退款主管审批"
    legacy = RetrievalCandidate(
        qa_pair_id="legacy",
        document_id="doc",
        question=query,
        answer="历史 QA 答案",
        quote=None,
        page_no=1,
        pair_index=0,
        vector_score=0.2,
        text_score=0.3,
        rrf_score=0.1,
        # These fields must not affect the flag-off, legacy QA path.
        title_path=("不应参与旧路径",),
        content="不应参与旧路径",
    )
    title_and_content_match = RetrievalCandidate(
        qa_pair_id=None,
        document_id="doc",
        question="generic chunk label",
        answer="generic answer",
        quote=None,
        page_no=2,
        pair_index=1,
        vector_score=0.2,
        text_score=0.3,
        rrf_score=0.1,
        evidence_id="chunk-match",
        evidence_type="CHUNK",
        chunk_id="chunk-match",
        title_path=("退款审批",),
        content="主管审批后方可退款",
    )
    generic_chunk = RetrievalCandidate(
        qa_pair_id=None,
        document_id="doc",
        question="generic chunk label",
        answer="generic answer",
        quote=None,
        page_no=3,
        pair_index=1,
        vector_score=0.2,
        text_score=0.3,
        rrf_score=0.1,
        evidence_id="chunk-generic",
        evidence_type="CHUNK",
        chunk_id="chunk-generic",
        title_path=("归档",),
        content="无关内容",
    )

    ranked = RerankService().rerank(query, [generic_chunk, legacy, title_and_content_match])

    by_id = {item.evidence_id or item.qa_pair_id: item for item in ranked}
    assert by_id["chunk-match"].rerank_score > by_id["chunk-generic"].rerank_score
    # Original QA formula: rrf*8 + vector*.35 + text*.45 + exact*1.2 + overlap*.5 + position*.15.
    assert by_id["legacy"].rerank_score == 2.855
