from pydantic import BaseModel, Field, field_validator


class OpenAIChatMessage(BaseModel):
    role: str
    content: str


class OpenAIChatCompletionRequest(BaseModel):
    model: str = Field(min_length=1)
    messages: list[OpenAIChatMessage] = Field(min_length=1)
    stream: bool = False
    metadata: dict | None = None

    @field_validator("messages")
    @classmethod
    def must_have_user_message(cls, value: list[OpenAIChatMessage]):
        if not any(item.role == "user" and item.content.strip() for item in value):
            raise ValueError("messages must contain a non-empty user message")
        return value
