from pydantic import BaseModel, ConfigDict, Field


class ClassificationPathResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    space_id: str | None = Field(default=None, alias="spaceId")
    space_name: str | None = Field(default=None, alias="spaceName")
    classification_department_id: str | None = Field(
        default=None, alias="classificationDepartmentId"
    )
    classification_department_name: str | None = Field(
        default=None, alias="classificationDepartmentName"
    )
    category_id: str | None = Field(default=None, alias="categoryId")
    category_name: str | None = Field(default=None, alias="categoryName")
    display_path: str = Field(alias="displayPath")
