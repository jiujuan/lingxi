from pydantic import BaseModel, ConfigDict, Field


class PaginationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    page: int
    page_size: int = Field(alias="pageSize")
    total_items: int = Field(alias="totalItems")
    total_pages: int = Field(alias="totalPages")


class TaskRunLogResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    task_type: str = Field(alias="taskType")
    queue_name: str = Field(alias="queueName")
    resource_type: str = Field(alias="resourceType")
    resource_id: str = Field(alias="resourceId")
    stage: str | None
    status: str
    error: dict | None
    error_code: str | None = Field(alias="errorCode")
    error_summary: str | None = Field(alias="errorSummary")
    retryable: bool
    request_id: str | None = Field(alias="requestId")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")


class TaskRunLogListResponse(BaseModel):
    data: list[TaskRunLogResponse]
    pagination: PaginationResponse


class ModelCallLogResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    provider_id: str | None = Field(alias="providerId")
    provider_name: str | None = Field(alias="providerName")
    model_config_id: str | None = Field(alias="modelConfigId")
    model_name: str | None = Field(alias="modelName")
    run_id: str | None = Field(alias="runId")
    capability: str
    status: str
    latency_ms: int | None = Field(alias="latencyMs")
    token_usage: dict = Field(alias="tokenUsage")
    error_code: str | None = Field(alias="errorCode")
    error_message: str | None = Field(alias="errorMessage")
    request_id: str | None = Field(alias="requestId")
    created_at: str = Field(alias="createdAt")


class ModelCallLogListResponse(BaseModel):
    data: list[ModelCallLogResponse]
    pagination: PaginationResponse


class ApiCallLogResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    key_prefix: str | None = Field(alias="keyPrefix")
    path: str
    method: str
    status_code: int = Field(alias="statusCode")
    latency_ms: int = Field(alias="latencyMs")
    error_code: str | None = Field(alias="errorCode")
    request_id: str | None = Field(alias="requestId")
    request_metadata: dict = Field(alias="requestMetadata")
    created_at: str = Field(alias="createdAt")


class ApiCallLogListResponse(BaseModel):
    data: list[ApiCallLogResponse]
    pagination: PaginationResponse


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    actor_id: str | None = Field(alias="actorId")
    action: str
    resource_type: str = Field(alias="resourceType")
    resource_id: str | None = Field(alias="resourceId")
    before_snapshot: dict | None = Field(alias="beforeSnapshot")
    after_snapshot: dict | None = Field(alias="afterSnapshot")
    request_id: str | None = Field(alias="requestId")
    created_at: str = Field(alias="createdAt")


class AuditLogListResponse(BaseModel):
    data: list[AuditLogResponse]
    pagination: PaginationResponse

