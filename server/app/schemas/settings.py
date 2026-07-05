from pydantic import BaseModel, ConfigDict, Field


class FilePolicy(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    max_file_size_mb: int = Field(alias="maxFileSizeMb", ge=1, le=1024)
    allowed_extensions: list[str] = Field(alias="allowedExtensions", min_length=1)
    default_parser: str = Field(alias="defaultParser", min_length=1)
    ocr_enabled: bool = Field(alias="ocrEnabled")
    fallback_enabled: bool = Field(alias="fallbackEnabled")


class RetrievalPolicy(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    vector_top_k: int = Field(alias="vectorTopK", ge=1, le=100)
    text_top_k: int = Field(alias="textTopK", ge=1, le=100)
    final_top_k: int = Field(alias="finalTopK", ge=1, le=20)
    low_confidence_threshold: float = Field(alias="lowConfidenceThreshold", ge=0, le=2)


class RateLimitPolicy(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_key_default_per_minute: int = Field(alias="apiKeyDefaultPerMinute", ge=1, le=10000)
    chat_per_minute: int = Field(alias="chatPerMinute", ge=1, le=10000)


class StoragePolicy(BaseModel):
    backend: str = Field(min_length=1)
    bucket: str | None = None
    prefix: str = ""


class RetentionPolicy(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_call_log_days: int = Field(alias="apiCallLogDays", ge=1, le=3650)
    audit_log_days: int = Field(alias="auditLogDays", ge=30, le=3650)
    task_run_days: int = Field(alias="taskRunDays", ge=1, le=3650)
    soft_delete_days: int = Field(alias="softDeleteDays", ge=1, le=3650)


class SystemSettingsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    file_policy: FilePolicy = Field(alias="filePolicy")
    retrieval_policy: RetrievalPolicy = Field(alias="retrievalPolicy")
    rate_limit_policy: RateLimitPolicy = Field(alias="rateLimitPolicy")
    storage_policy: StoragePolicy = Field(alias="storagePolicy")
    retention_policy: RetentionPolicy = Field(alias="retentionPolicy")
    effective_scopes: dict[str, str] = Field(alias="effectiveScopes")

