from pydantic import BaseModel, ConfigDict, Field


class PaginationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    page: int
    page_size: int = Field(alias="pageSize")
    total_items: int = Field(alias="totalItems")
    total_pages: int = Field(alias="totalPages")


class QaPairResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    document_id: str = Field(alias="documentId")
    chunk_id: str | None = Field(alias="chunkId")
    question: str
    answer: str
    quote: str | None
    page_no: int | None = Field(alias="pageNo")
    embedding_status: str = Field(alias="embeddingStatus")
    status: str


class QaPairListResponse(BaseModel):
    data: list[QaPairResponse]
    pagination: PaginationResponse


class QaRegenerationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    document_id: str | None = Field(alias="documentId")
    status: str
    stage: str
    progress: int
    error_code: str | None = Field(alias="errorCode")
    error_message: str | None = Field(alias="errorMessage")
