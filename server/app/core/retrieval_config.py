from dataclasses import dataclass

from server.app.core.config import Settings, settings


@dataclass(frozen=True)
class RetrievalConfig:
    vector_top_k: int
    text_top_k: int
    hybrid_qa_vector_top_k: int
    hybrid_chunk_vector_top_k: int
    hybrid_qa_text_top_k: int
    hybrid_chunk_text_top_k: int
    final_top_k: int
    rrf_k: int
    low_confidence_threshold: float
    snapshot_max_items_per_stage: int


def get_retrieval_config(current: Settings | None = None) -> RetrievalConfig:
    current = current or settings
    return RetrievalConfig(
        vector_top_k=current.retrieval_vector_top_k,
        text_top_k=current.retrieval_text_top_k,
        hybrid_qa_vector_top_k=current.retrieval_hybrid_qa_vector_top_k,
        hybrid_chunk_vector_top_k=current.retrieval_hybrid_chunk_vector_top_k,
        hybrid_qa_text_top_k=current.retrieval_hybrid_qa_text_top_k,
        hybrid_chunk_text_top_k=current.retrieval_hybrid_chunk_text_top_k,
        final_top_k=current.retrieval_final_top_k,
        rrf_k=current.retrieval_rrf_k,
        low_confidence_threshold=current.retrieval_low_confidence_threshold,
        snapshot_max_items_per_stage=current.retrieval_snapshot_max_items_per_stage,
    )
