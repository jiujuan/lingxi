from pydantic import BaseModel, ConfigDict, Field


class QaSplitResultItem(BaseModel):
    """The only model output shape allowed in a persisted QA checkpoint."""

    model_config = ConfigDict(populate_by_name=True)

    question: str
    answer: str
    quote: str
    page_no: int = Field(alias="pageNo")
    chunk_index: int = Field(alias="chunkIndex")


class QaSplitBatchResultPayload(BaseModel):
    """Validated, structured checkpoint data without prompts or raw output."""

    items: list[QaSplitResultItem]


class QaSplitBatchFailurePayload(BaseModel):
    """Minimal retry state for a failed batch."""

    retryable: bool
