from pydantic import BaseModel, ConfigDict, Field


class ModelProviderCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider_type: str = Field(alias="providerType")
    name: str = Field(min_length=1, max_length=160)
    base_url: str | None = Field(default=None, alias="baseUrl")
    api_key: str | None = Field(default=None, alias="apiKey")
    status: str = "ACTIVE"
    config: dict = Field(default_factory=dict)


class ModelProviderUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=160)
    base_url: str | None = Field(default=None, alias="baseUrl")
    api_key: str | None = Field(default=None, alias="apiKey")
    status: str | None = None
    config: dict | None = None


class ModelProviderResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    provider_type: str = Field(alias="providerType")
    name: str
    base_url: str | None = Field(alias="baseUrl")
    status: str
    config: dict
    secret_configured: bool = Field(alias="secretConfigured")


class ModelProviderListResponse(BaseModel):
    data: list[ModelProviderResponse]


class ConnectionTestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    model_config_id: str | None = Field(default=None, alias="modelConfigId")


class ConnectionTestResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    success: bool
    status: str
    latency_ms: int = Field(alias="latencyMs")
    error_code: str | None = Field(alias="errorCode")
    error_message: str | None = Field(alias="errorMessage")
    provider_name: str | None = Field(default=None, alias="providerName")
    provider_type: str | None = Field(default=None, alias="providerType")
    model_config_id: str | None = Field(default=None, alias="modelConfigId")
    model_name: str | None = Field(default=None, alias="modelName")
    endpoint: str | None = None
    timeout_ms: int | None = Field(default=None, alias="timeoutMs")
    timeout_phase: str | None = Field(default=None, alias="timeoutPhase")


class ModelConfigCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider_id: str = Field(alias="providerId")
    capability: str
    model_name: str = Field(alias="modelName", min_length=1, max_length=160)
    embedding_dimension: int | None = Field(default=None, alias="embeddingDimension")
    max_tokens: int | None = Field(default=None, alias="maxTokens")
    timeout_ms: int | bool = Field(default=30000, alias="timeoutMs")
    connect_timeout_ms: int | bool | None = Field(
        default=None, alias="connectTimeoutMs"
    )
    write_timeout_ms: int | bool | None = Field(
        default=None, alias="writeTimeoutMs"
    )
    read_idle_timeout_ms: int | bool | None = Field(
        default=None, alias="readIdleTimeoutMs"
    )
    overall_timeout_ms: int | bool | None = Field(
        default=None, alias="overallTimeoutMs"
    )
    is_default: bool = Field(default=False, alias="isDefault")
    status: str = "ACTIVE"
    config: dict = Field(default_factory=dict)


class ModelConfigUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    model_name: str | None = Field(default=None, alias="modelName")
    embedding_dimension: int | None = Field(default=None, alias="embeddingDimension")
    max_tokens: int | None = Field(default=None, alias="maxTokens")
    timeout_ms: int | bool | None = Field(default=None, alias="timeoutMs")
    connect_timeout_ms: int | bool | None = Field(
        default=None, alias="connectTimeoutMs"
    )
    write_timeout_ms: int | bool | None = Field(
        default=None, alias="writeTimeoutMs"
    )
    read_idle_timeout_ms: int | bool | None = Field(
        default=None, alias="readIdleTimeoutMs"
    )
    overall_timeout_ms: int | bool | None = Field(
        default=None, alias="overallTimeoutMs"
    )
    is_default: bool | None = Field(default=None, alias="isDefault")
    status: str | None = None
    config: dict | None = None


class ModelConfigResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    provider_id: str = Field(alias="providerId")
    capability: str
    model_name: str = Field(alias="modelName")
    embedding_dimension: int | None = Field(alias="embeddingDimension")
    max_tokens: int | None = Field(alias="maxTokens")
    timeout_ms: int = Field(alias="timeoutMs")
    connect_timeout_ms: int | None = Field(alias="connectTimeoutMs")
    write_timeout_ms: int | None = Field(alias="writeTimeoutMs")
    read_idle_timeout_ms: int | None = Field(alias="readIdleTimeoutMs")
    overall_timeout_ms: int | None = Field(alias="overallTimeoutMs")
    is_default: bool = Field(alias="isDefault")
    status: str
    config: dict


class ModelConfigListResponse(BaseModel):
    data: list[ModelConfigResponse]
