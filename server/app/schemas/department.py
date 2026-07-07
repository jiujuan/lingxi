from pydantic import BaseModel, ConfigDict, Field


class DepartmentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=80)
    parent_id: str | None = Field(default=None, alias="parentId")


class DepartmentUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=80)
    parent_id: str | None = Field(default=None, alias="parentId")


class DepartmentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    code: str
    parent_id: str | None = Field(alias="parentId")
    user_count: int = Field(alias="userCount")
    created_at: str = Field(alias="createdAt")


class DepartmentListResponse(BaseModel):
    data: list[DepartmentResponse]
