from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from server.app.models.knowledge_category import KnowledgeCategoryType


class NamedClassificationNodeResponse(BaseModel):
    id: str
    name: str
    code: str


class KnowledgeSpaceCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=80)
    description: str | None = None
    status: str = Field(default="ACTIVE", min_length=1, max_length=40)
    sort_order: int = Field(default=0, alias="sortOrder")


class KnowledgeSpaceUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    code: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    status: str | None = Field(default=None, min_length=1, max_length=40)
    sort_order: int | None = Field(default=None, alias="sortOrder")


class KnowledgeSpaceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    code: str
    description: str | None
    status: str
    sort_order: int = Field(alias="sortOrder")
    created_at: datetime | None = Field(alias="createdAt")
    updated_at: datetime | None = Field(alias="updatedAt")


class KnowledgeSpaceListResponse(BaseModel):
    data: list[KnowledgeSpaceResponse]


class KnowledgeClassificationStatsRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_count: int = Field(alias="totalCount")
    processing_count: int = Field(alias="processingCount")
    ready_count: int = Field(alias="readyCount")
    failed_count: int = Field(alias="failedCount")
    unclassified_count: int = Field(alias="unclassifiedCount")


class KnowledgeSpaceStatsRead(KnowledgeClassificationStatsRead):
    space_id: str = Field(alias="spaceId")


class KnowledgeCategoryStatsRead(KnowledgeClassificationStatsRead):
    category_id: str = Field(alias="categoryId")
    space_id: str = Field(alias="spaceId")
    department_id: str = Field(alias="departmentId")


class KnowledgeSpaceStatsListResponse(BaseModel):
    data: list[KnowledgeSpaceStatsRead]
    summary: KnowledgeClassificationStatsRead


class KnowledgeCategoryStatsListResponse(BaseModel):
    data: list[KnowledgeCategoryStatsRead]
    unclassified: KnowledgeClassificationStatsRead


class KnowledgeCategoryCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    space_id: str = Field(alias="spaceId")
    department_id: str = Field(alias="departmentId")
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=80)
    category_type: KnowledgeCategoryType = Field(
        default=KnowledgeCategoryType.TOPIC, alias="categoryType"
    )
    parent_id: str | None = Field(default=None, alias="parentId")
    description: str | None = None
    sort_order: int = Field(default=0, alias="sortOrder")
    status: str = Field(default="ACTIVE", min_length=1, max_length=40)


class KnowledgeCategoryUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    space_id: str | None = Field(default=None, alias="spaceId")
    department_id: str | None = Field(default=None, alias="departmentId")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    code: str | None = Field(default=None, min_length=1, max_length=80)
    category_type: KnowledgeCategoryType | None = Field(
        default=None, alias="categoryType"
    )
    parent_id: str | None = Field(default=None, alias="parentId")
    description: str | None = None
    sort_order: int | None = Field(default=None, alias="sortOrder")
    status: str | None = Field(default=None, min_length=1, max_length=40)


class KnowledgeCategoryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    space_id: str = Field(alias="spaceId")
    department_id: str = Field(alias="departmentId")
    name: str
    code: str
    category_type: KnowledgeCategoryType = Field(alias="categoryType")
    parent_id: str | None = Field(alias="parentId")
    description: str | None
    sort_order: int = Field(alias="sortOrder")
    status: str
    created_at: datetime | None = Field(alias="createdAt")
    updated_at: datetime | None = Field(alias="updatedAt")


class KnowledgeCategoryListResponse(BaseModel):
    data: list[KnowledgeCategoryResponse]


class DocumentClassificationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    knowledge_space_id: str | None = Field(default=None, alias="knowledgeSpaceId")
    category_department_id: str | None = Field(
        default=None, alias="categoryDepartmentId"
    )
    knowledge_category_id: str | None = Field(
        default=None, alias="knowledgeCategoryId"
    )


class DocumentClassificationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    knowledge_space_id: str | None = Field(alias="knowledgeSpaceId")
    category_department_id: str | None = Field(alias="categoryDepartmentId")
    knowledge_category_id: str | None = Field(alias="knowledgeCategoryId")
    knowledge_space: NamedClassificationNodeResponse | None = Field(
        alias="knowledgeSpace"
    )
    category_department: NamedClassificationNodeResponse | None = Field(
        alias="categoryDepartment"
    )
    knowledge_category: NamedClassificationNodeResponse | None = Field(
        alias="knowledgeCategory"
    )
