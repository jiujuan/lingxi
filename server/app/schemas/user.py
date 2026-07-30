from pydantic import BaseModel, ConfigDict, Field, field_validator

from server.app.schemas.logs import PaginationResponse


def _normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if "@" not in normalized:
        raise ValueError("邮箱格式不合法")
    return normalized


class UserCreateRequest(BaseModel):
    email: str
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    department_id: str | None = Field(default=None, alias="departmentId")
    role_ids: list[str] = Field(default_factory=list, alias="roleIds")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class UserUpdateRequest(BaseModel):
    email: str
    name: str = Field(min_length=1, max_length=120)
    department_id: str | None = Field(default=None, alias="departmentId")
    role_ids: list[str] = Field(default_factory=list, alias="roleIds")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_email(value)


class UserResetPasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class RoleResponse(BaseModel):
    id: str
    code: str
    name: str


class AdminUserResponse(BaseModel):
    """Response for 用户管理 endpoints; named to avoid clashing with auth.UserResponse."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    email: str
    name: str
    status: str
    department_id: str | None = Field(alias="departmentId")
    department_name: str | None = Field(alias="departmentName")
    roles: list[RoleResponse]
    created_at: str = Field(alias="createdAt")


class UserListResponse(BaseModel):
    data: list[AdminUserResponse]
    pagination: PaginationResponse
