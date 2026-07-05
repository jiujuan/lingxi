from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    scopes: list[str] = Field(default_factory=list)
    allowed_department_ids: list[str] = Field(default_factory=list, alias="allowedDepartmentIds")
    allowed_role_ids: list[str] = Field(default_factory=list, alias="allowedRoleIds")
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10000, alias="rateLimitPerMinute")
    expires_at: datetime | None = Field(default=None, alias="expiresAt")


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    key_prefix: str = Field(alias="keyPrefix")
    status: str
    scopes: list[str]
    allowed_department_ids: list[str] = Field(alias="allowedDepartmentIds")
    allowed_role_ids: list[str] = Field(alias="allowedRoleIds")
    rate_limit_per_minute: int = Field(alias="rateLimitPerMinute")
    last_used_at: str | None = Field(alias="lastUsedAt")
    expires_at: str | None = Field(alias="expiresAt")
    created_at: str = Field(alias="createdAt")


class ApiKeyListResponse(BaseModel):
    data: list[ApiKeyResponse]


class ApiKeyCreateResponse(ApiKeyResponse):
    key: str
    warning: str


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
    created_at: str = Field(alias="createdAt")


class ApiCallLogListResponse(BaseModel):
    data: list[ApiCallLogResponse]
