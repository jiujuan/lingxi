from dataclasses import dataclass, field

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


@dataclass
class RetrievalCandidate:
    qa_pair_id: str
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

    def to_snapshot(self) -> dict:
        return {
            "qaPairId": self.qa_pair_id,
            "documentId": self.document_id,
            "question": self.question,
            "pageNo": self.page_no,
            "vectorScore": round(self.vector_score, 6),
            "textScore": round(self.text_score, 6),
            "rrfScore": round(self.rrf_score, 6),
            "rerankScore": round(self.rerank_score, 6),
        }


@dataclass
class RetrievalResult:
    question: str
    candidates: list[RetrievalCandidate]
    has_answer: bool
    confidence: float
    snapshot: dict = field(default_factory=dict)
