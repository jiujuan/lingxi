from dataclasses import dataclass

from server.app.core.config import settings


@dataclass(frozen=True)
class RetrievalConfig:
    vector_top_k: int
    text_top_k: int
    final_top_k: int
    rrf_k: int
    low_confidence_threshold: float
    snapshot_max_items_per_stage: int


def get_retrieval_config() -> RetrievalConfig:
    return RetrievalConfig(
        vector_top_k=settings.retrieval_vector_top_k,
        text_top_k=settings.retrieval_text_top_k,
        final_top_k=settings.retrieval_final_top_k,
        rrf_k=settings.retrieval_rrf_k,
        low_confidence_threshold=settings.retrieval_low_confidence_threshold,
        snapshot_max_items_per_stage=settings.retrieval_snapshot_max_items_per_stage,
    )
