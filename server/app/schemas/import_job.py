from pydantic import BaseModel, ConfigDict, Field


class ImportPermissionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    department_ids: list[str] = Field(default_factory=list, alias="departmentIds")
    role_ids: list[str] = Field(default_factory=list, alias="roleIds")
    user_ids: list[str] = Field(default_factory=list, alias="userIds")
    all_authenticated: bool = Field(default=False, alias="allAuthenticated")


class ImportClassificationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    knowledge_space_id: str | None = Field(default=None, alias="spaceId")
    category_department_id: str | None = Field(default=None, alias="departmentId")
    knowledge_category_id: str | None = Field(default=None, alias="categoryId")


class ImportJobCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(min_length=1, max_length=300)
    classification: ImportClassificationRequest | None = None
    permission: ImportPermissionRequest = Field(
        default_factory=ImportPermissionRequest
    )
    parse_options: dict = Field(default_factory=dict, alias="parseOptions")
    processing_options: dict = Field(default_factory=dict, alias="processingOptions")


class ImportJobFileBindRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    object_key: str = Field(alias="objectKey")
    file_name: str = Field(alias="fileName", min_length=1, max_length=300)
    mime_type: str = Field(alias="mimeType", min_length=1, max_length=160)
    file_size: int = Field(alias="fileSize", ge=0)
    checksum: str = Field(min_length=1, max_length=128)
    content_base64: str | None = Field(default=None, alias="contentBase64")


class ImportJobFileResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    object_key: str = Field(alias="objectKey")
    file_name: str = Field(alias="fileName")
    mime_type: str = Field(alias="mimeType")
    file_size: int = Field(alias="fileSize")
    checksum: str


class ImportJobResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    document_id: str | None = Field(alias="documentId")
    status: str
    stage: str
    progress: int
    retry_count: int = Field(alias="retryCount")
    error_code: str | None = Field(alias="errorCode")
    error_message: str | None = Field(alias="errorMessage")
    failed_stage: str | None = Field(default=None, alias="failedStage")
    retryable: bool = False
    file: ImportJobFileResponse | None = None
