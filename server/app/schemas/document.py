from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from server.app.schemas.qa_pair import PaginationResponse


class NamedSubjectResponse(BaseModel):
    id: str
    name: str


class DocumentPermissionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    department_ids: list[str] = Field(default_factory=list, alias="departmentIds")
    role_ids: list[str] = Field(default_factory=list, alias="roleIds")
    user_ids: list[str] = Field(default_factory=list, alias="userIds")
    all_authenticated: bool = Field(default=False, alias="allAuthenticated")


class DocumentPermissionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    all_authenticated: bool = Field(alias="allAuthenticated")
    departments: list[NamedSubjectResponse]
    roles: list[NamedSubjectResponse]
    users: list[NamedSubjectResponse]


class DocumentJobSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    status: str
    stage: str
    progress: int
    retry_count: int = Field(alias="retryCount")
    error_code: str | None = Field(alias="errorCode")
    error_message: str | None = Field(alias="errorMessage")
    failed_stage: str | None = Field(alias="failedStage")
    retryable: bool


class ProcessingLogResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    task_type: str = Field(alias="taskType")
    queue_name: str = Field(alias="queueName")
    stage: str | None
    status: str
    error: dict[str, Any] | None
    request_id: str | None = Field(alias="requestId")


class DocumentListItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    file_name: str = Field(alias="fileName")
    file_type: str = Field(alias="fileType")
    mime_type: str = Field(alias="mimeType")
    file_size: int = Field(alias="fileSize")
    status: str
    parser_name: str | None = Field(alias="parserName")
    page_count: int | None = Field(alias="pageCount")
    qa_pair_count: int = Field(alias="qaPairCount")
    chunk_count: int = Field(alias="chunkCount")
    permissions: DocumentPermissionResponse
    latest_job: DocumentJobSummaryResponse | None = Field(alias="latestJob")
    last_error_code: str | None = Field(alias="lastErrorCode")
    last_error_message: str | None = Field(alias="lastErrorMessage")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class DocumentListResponse(BaseModel):
    data: list[DocumentListItemResponse]
    pagination: PaginationResponse


class DocumentDetailResponse(DocumentListItemResponse):
    parser_version: str | None = Field(alias="parserVersion")
    object_key: str = Field(alias="objectKey")
    checksum: str
    processing_logs: list[ProcessingLogResponse] = Field(alias="processingLogs")


class DocumentChunkResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    document_id: str = Field(alias="documentId")
    chunk_index: int = Field(alias="chunkIndex")
    title_path: list = Field(alias="titlePath")
    content: str
    page_no: int | None = Field(alias="pageNo")
    token_count: int = Field(alias="tokenCount")
    source_locator: dict = Field(alias="sourceLocator")
    status: str


class DocumentChunkListResponse(BaseModel):
    data: list[DocumentChunkResponse]
    pagination: PaginationResponse


class DocumentDeleteResponse(BaseModel):
    id: str
    status: str
