from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class RetrievalAccessScope:
    document_ids: set[str] | None = None
    space_id: str | None = None
    classification_department_id: str | None = None
    category_id: str | None = None


class RetrievalAccessScopeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    space_id: str | None = Field(default=None, alias="spaceId")
    classification_department_id: str | None = Field(
        default=None, alias="classificationDepartmentId"
    )
    category_id: str | None = Field(default=None, alias="categoryId")

    def to_access_scope(
        self, document_ids: set[str] | None = None
    ) -> RetrievalAccessScope:
        return RetrievalAccessScope(
            document_ids=document_ids,
            space_id=self.space_id,
            classification_department_id=self.classification_department_id,
            category_id=self.category_id,
        )


@dataclass(frozen=True)
class RetrievalEvidence:
    """A source-Chunk-centric retrieval item used by hybrid retrieval.

    ``qa_pair_id``/``question``/``answer`` retain QA query-expansion metadata.
    They are deliberately optional so an original Child Chunk can be retrieved
    even when no generated QA pair exists for it.
    """

    evidence_type: Literal["QA", "CHUNK"]
    evidence_id: str
    document_id: str
    chunk_id: str
    parent_chunk_id: str | None
    content: str
    quote: str | None
    title_path: tuple[str, ...]
    page_start: int | None
    page_end: int | None
    source_locator: dict | list[dict]
    channel_scores: dict[str, float]
    fused_score: float
    channel_ranks: dict[str, int] = field(default_factory=dict)
    content_hash: str | None = None
    qa_pair_id: str | None = None
    question: str | None = None
    answer: str | None = None
    pair_index: int = 0

    def to_candidate(self) -> "RetrievalCandidate":
        title = " / ".join(self.title_path)
        return RetrievalCandidate(
            qa_pair_id=self.qa_pair_id,
            document_id=self.document_id,
            question=self.question or title or self.content,
            answer=self.content,
            quote=self.quote,
            page_no=self.page_start,
            pair_index=self.pair_index,
            vector_score=self.channel_scores.get("qa_vector", 0.0),
            text_score=self.channel_scores.get("qa_text", 0.0),
            rrf_score=self.fused_score,
            source_rank=min(self.channel_ranks.values(), default=None),
            evidence_id=self.evidence_id,
            evidence_type=self.evidence_type,
            chunk_id=self.chunk_id,
            parent_chunk_id=self.parent_chunk_id,
            content=self.content,
            title_path=self.title_path,
            page_start=self.page_start,
            page_end=self.page_end,
            source_locator=self.source_locator,
            channel_scores=dict(self.channel_scores),
            channel_ranks=dict(self.channel_ranks),
            fused_score=self.fused_score,
        )


@dataclass
class RetrievalCandidate:
    """Legacy response shape with optional unified-evidence metadata.

    Existing callers continue to use QA-oriented fields.  Hybrid retrieval
    adds the optional source Chunk fields instead of replacing those fields.
    """

    qa_pair_id: str | None
    document_id: str
    question: str
    answer: str
    quote: str | None
    page_no: int | None
    pair_index: int
    vector_score: float = 0.0
    text_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: float = 0.0
    source_rank: int | None = None
    evidence_id: str | None = None
    evidence_type: Literal["QA", "CHUNK"] | None = None
    chunk_id: str | None = None
    parent_chunk_id: str | None = None
    content: str | None = None
    title_path: tuple[str, ...] = ()
    page_start: int | None = None
    page_end: int | None = None
    source_locator: dict | list[dict] | None = None
    channel_scores: dict[str, float] = field(default_factory=dict)
    channel_ranks: dict[str, int] = field(default_factory=dict)
    fused_score: float = 0.0

    def to_snapshot(self) -> dict:
        # Preserve the original public snapshot fields for legacy consumers.
        snapshot = {
            "qaPairId": self.qa_pair_id,
            "documentId": self.document_id,
            "question": self.question,
            "pageNo": self.page_no,
            "vectorScore": round(self.vector_score, 6),
            "textScore": round(self.text_score, 6),
            "rrfScore": round(self.rrf_score, 6),
            "rerankScore": round(self.rerank_score, 6),
        }
        if self.evidence_id is not None:
            snapshot.update(
                {
                    "evidenceId": self.evidence_id,
                    "evidenceType": self.evidence_type,
                    "chunkId": self.chunk_id,
                    "parentChunkId": self.parent_chunk_id,
                    "pageStart": self.page_start,
                    "pageEnd": self.page_end,
                    "titlePath": list(self.title_path),
                    "channelScores": {
                        name: round(score, 6)
                        for name, score in self.channel_scores.items()
                    },
                    "channelRanks": dict(self.channel_ranks),
                    "fusedScore": round(self.fused_score, 6),
                }
            )
        return snapshot


@dataclass
class RetrievalResult:
    question: str
    candidates: list[RetrievalCandidate]
    has_answer: bool
    confidence: float
    snapshot: dict = field(default_factory=dict)
