from pydantic import BaseModel, ConfigDict, Field


class CitationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    run_id: str = Field(alias="runId")
    document_id: str | None = Field(alias="documentId")
    qa_pair_id: str | None = Field(alias="qaPairId")
    title: str | None
    page_no: int | None = Field(alias="pageNo")
    quote: str
    rank: int
    score: float


class CitationListResponse(BaseModel):
    data: list[CitationResponse]


class CitationSourceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    citation_id: str = Field(alias="citationId")
    document_id: str | None = Field(alias="documentId")
    document_title: str | None = Field(alias="documentTitle")
    document_deleted: bool = Field(alias="documentDeleted")
    page_no: int | None = Field(alias="pageNo")
    quote: str
    source_text: str = Field(alias="sourceText")
    source_locator: dict = Field(alias="sourceLocator")
