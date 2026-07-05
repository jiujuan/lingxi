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
