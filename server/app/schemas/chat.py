from pydantic import BaseModel, ConfigDict, Field

from server.app.schemas.retrieval import RetrievalAccessScope, RetrievalAccessScopeRequest


class ChatSessionCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class ChatRetrievalScope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    space_id: str | None = Field(default=None, alias="spaceId")
    classification_department_id: str | None = Field(
        default=None, alias="classificationDepartmentId"
    )
    category_id: str | None = Field(default=None, alias="categoryId")
    classification: RetrievalAccessScopeRequest | None = None

    def to_access_scope(self) -> RetrievalAccessScope | None:
        source = self.classification or self
        if not (
            source.space_id
            or source.classification_department_id
            or source.category_id
        ):
            return None
        return RetrievalAccessScope(
            space_id=source.space_id,
            classification_department_id=source.classification_department_id,
            category_id=source.category_id,
        )


class ChatMessageRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    content: str = Field(min_length=1, max_length=4000)
    retrieval_scope: ChatRetrievalScope | None = Field(
        default=None, alias="retrievalScope"
    )


class ChatFeedbackRequest(BaseModel):
    feedback: str = Field(pattern="^(up|down)$")


class ChatSessionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str | None
    status: str
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")


class ChatSessionListResponse(BaseModel):
    data: list[ChatSessionResponse]


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    session_id: str = Field(alias="sessionId")
    role: str
    content: str
    status: str
    request_id: str | None = Field(alias="requestId")
    created_at: str = Field(alias="createdAt")


class ChatMessageListResponse(BaseModel):
    data: list[ChatMessageResponse]
