from pydantic import BaseModel, ConfigDict, Field


class ChatSessionCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class ChatMessageRunRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


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
