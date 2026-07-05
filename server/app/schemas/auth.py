from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized:
            raise ValueError("邮箱格式不合法")
        return normalized


class UserResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    tenant_id: str = Field(alias="tenantId")
    department_id: str | None = Field(alias="departmentId")
    email: str
    name: str
    roles: list[str]
    permissions: list[str]


class TokenResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: str = Field(alias="accessToken")
    refresh_token: str = Field(alias="refreshToken")
    expires_in: int = Field(alias="expiresIn")
    user: UserResponse


class RefreshRequest(BaseModel):
    refresh_token: str = Field(alias="refreshToken")
