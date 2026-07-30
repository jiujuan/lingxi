from pydantic import BaseModel, ConfigDict, Field, field_validator

from server.app.schemas.logs import PaginationResponse


class RoleUpsertRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=80)
    permission_ids: list[str] = Field(default_factory=list, alias="permissionIds")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("角色名称不能为空")
        return normalized

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("角色编码不能为空")
        return normalized


class PermissionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    code: str
    module: str
    action: str
    description: str | None


class RoleOptionResponse(BaseModel):
    """Lightweight tenant role data used by the user-assignment form."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    code: str
    name: str


class RoleOptionsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: list[RoleOptionResponse]


class RoleListItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    code: str
    scope: str
    is_builtin: bool = Field(alias="isBuiltin")
    user_count: int = Field(alias="userCount")
    permission_count: int = Field(alias="permissionCount")
    created_at: str = Field(alias="createdAt")


class RoleDetailResponse(RoleListItemResponse):
    permissions: list[PermissionResponse]


class RoleListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    data: list[RoleListItemResponse]
    pagination: PaginationResponse


class PermissionCatalogResponse(BaseModel):
    data: list[PermissionResponse]