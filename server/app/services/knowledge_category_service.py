from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.app.core.errors import bad_request, conflict, not_found
from server.app.core.ids import current_request_id
from server.app.core.permissions import AccessContext
from server.app.models.knowledge_category import (
    KnowledgeCategory,
    KnowledgeCategoryType,
    KnowledgeSpace,
)
from server.app.models.logs import AuditLog
from server.app.models.user import Department
from server.app.repositories.department_repo import DepartmentRepository
from server.app.repositories.knowledge_category_repo import (
    KnowledgeCategoryRepository,
    KnowledgeSpaceRepository,
)

ACTIVE_STATUSES = {"ACTIVE", "INACTIVE"}


@dataclass(frozen=True)
class ValidatedClassification:
    knowledge_space: KnowledgeSpace | None
    category_department: Department | None
    knowledge_category: KnowledgeCategory | None


class KnowledgeCategoryService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.spaces = KnowledgeSpaceRepository(session)
        self.categories = KnowledgeCategoryRepository(session)
        self.departments = DepartmentRepository(session)

    def list_spaces(self, context: AccessContext) -> list[dict]:
        return [
            self._space_to_dict(space)
            for space in self.spaces.list_for_tenant(context.tenant_id)
        ]

    def list_space_stats(self, context: AccessContext) -> dict:
        stats_by_space = self.spaces.get_space_stats(context.tenant_id)
        data = []
        for space in self.spaces.list_for_tenant(context.tenant_id):
            data.append(
                {
                    "space_id": space.id,
                    **_zero_stats(),
                    **stats_by_space.get(space.id, {}),
                }
            )
        return {
            "data": data,
            "summary": self.categories.get_unclassified_stats(context.tenant_id),
        }

    def create_space(self, context: AccessContext, payload: Any) -> dict:
        data = self._payload_dict(payload)
        code = self._clean_code(data["code"])
        if self.spaces.get_by_code(context.tenant_id, code):
            raise conflict("KNOWLEDGE_SPACE_CODE_EXISTS", "知识库空间编码已存在")
        status = self._clean_status(data.get("status", "ACTIVE"))
        space = KnowledgeSpace(
            tenant_id=context.tenant_id,
            name=self._clean_name(data["name"]),
            code=code,
            description=self._clean_optional_text(data.get("description")),
            status=status,
            sort_order=int(data.get("sort_order", 0)),
        )
        self.spaces.add(space)
        self._audit(context, "KNOWLEDGE_SPACE_CREATED", "KNOWLEDGE_SPACE", space)
        self.session.commit()
        return self._space_to_dict(space)

    def update_space(
        self, context: AccessContext, space_id: str, payload: Any
    ) -> dict:
        space = self._require_space(context, space_id)
        before = self._space_public_dict(space)
        data = self._payload_dict(payload, exclude_unset=True)
        if "code" in data and data["code"] is not None:
            code = self._clean_code(data["code"])
            existing = self.spaces.get_by_code(context.tenant_id, code)
            if existing and existing.id != space.id:
                raise conflict("KNOWLEDGE_SPACE_CODE_EXISTS", "知识库空间编码已存在")
            space.code = code
        if "name" in data and data["name"] is not None:
            space.name = self._clean_name(data["name"])
        if "description" in data:
            space.description = self._clean_optional_text(data["description"])
        if "status" in data and data["status"] is not None:
            space.status = self._clean_status(data["status"])
        if "sort_order" in data and data["sort_order"] is not None:
            space.sort_order = int(data["sort_order"])
        self._audit(
            context,
            "KNOWLEDGE_SPACE_UPDATED",
            "KNOWLEDGE_SPACE",
            space,
            before,
        )
        self.session.commit()
        return self._space_to_dict(space)

    def delete_space(self, context: AccessContext, space_id: str) -> None:
        space = self._require_space(context, space_id)
        if self.spaces.count_documents(context.tenant_id, space.id):
            raise conflict("KNOWLEDGE_SPACE_HAS_DOCUMENTS", "请先移走空间下的文档")
        if self.categories.count_for_space(context.tenant_id, space.id):
            raise conflict("KNOWLEDGE_SPACE_HAS_CATEGORIES", "请先删除空间下的分类")
        before = self._space_public_dict(space)
        self._audit(
            context,
            "KNOWLEDGE_SPACE_DELETED",
            "KNOWLEDGE_SPACE",
            space,
            before,
        )
        self.spaces.delete(space)
        self.session.commit()

    def list_categories(
        self,
        context: AccessContext,
        space_id: str | None = None,
        department_id: str | None = None,
    ) -> list[dict]:
        if space_id:
            self._require_space(context, space_id)
        if department_id:
            self._require_department(context, department_id)
        return [
            self._category_to_dict(category)
            for category in self.categories.list_for_tenant(
                context.tenant_id,
                space_id=space_id,
                department_id=department_id,
            )
        ]

    def list_category_stats(
        self,
        context: AccessContext,
        space_id: str | None = None,
        department_id: str | None = None,
    ) -> dict:
        if space_id:
            self._require_space(context, space_id)
        if department_id:
            self._require_department(context, department_id)
        stats_by_category = self.categories.get_category_stats(
            context.tenant_id, space_id=space_id, department_id=department_id
        )
        data = []
        for category in self.categories.list_for_tenant(
            context.tenant_id, space_id=space_id, department_id=department_id
        ):
            data.append(
                {
                    "category_id": category.id,
                    "space_id": category.space_id,
                    "department_id": category.department_id,
                    **_zero_stats(),
                    **stats_by_category.get(category.id, {}),
                }
            )
        return {
            "data": data,
            "unclassified": self.categories.get_unclassified_stats(
                context.tenant_id, space_id=space_id, department_id=department_id
            ),
        }

    def create_category(self, context: AccessContext, payload: Any) -> dict:
        data = self._payload_dict(payload)
        space = self._require_space(context, data["space_id"])
        department = self._require_department(context, data["department_id"])
        code = self._clean_code(data["code"])
        if self.categories.get_by_code(
            context.tenant_id, space.id, department.id, code
        ):
            raise conflict("KNOWLEDGE_CATEGORY_CODE_EXISTS", "分类编码已存在")
        parent_id = data.get("parent_id")
        if parent_id:
            parent = self._require_category(context, parent_id)
            self._assert_parent_matches_path(parent, space.id, department.id)
        category = KnowledgeCategory(
            tenant_id=context.tenant_id,
            space_id=space.id,
            department_id=department.id,
            name=self._clean_name(data["name"]),
            code=code,
            category_type=self._clean_category_type(
                data.get("category_type", KnowledgeCategoryType.TOPIC)
            ),
            parent_id=parent_id,
            description=self._clean_optional_text(data.get("description")),
            sort_order=int(data.get("sort_order", 0)),
            status=self._clean_status(data.get("status", "ACTIVE")),
        )
        self.categories.add(category)
        self._audit(
            context,
            "KNOWLEDGE_CATEGORY_CREATED",
            "KNOWLEDGE_CATEGORY",
            category,
        )
        self.session.commit()
        return self._category_to_dict(category)

    def update_category(
        self, context: AccessContext, category_id: str, payload: Any
    ) -> dict:
        category = self._require_category(context, category_id)
        before = self._category_public_dict(category)
        data = self._payload_dict(payload, exclude_unset=True)
        space_id = data.get("space_id", category.space_id)
        department_id = data.get("department_id", category.department_id)
        self._require_space(context, space_id)
        self._require_department(context, department_id)

        if "code" in data and data["code"] is not None:
            code = self._clean_code(data["code"])
        else:
            code = category.code
        existing = self.categories.get_by_code(
            context.tenant_id, space_id, department_id, code
        )
        if existing and existing.id != category.id:
            raise conflict("KNOWLEDGE_CATEGORY_CODE_EXISTS", "分类编码已存在")

        if "parent_id" in data:
            parent_id = data["parent_id"]
        else:
            parent_id = category.parent_id
        if parent_id:
            self._assert_valid_parent(
                context, category, parent_id, space_id, department_id
            )

        category.space_id = space_id
        category.department_id = department_id
        category.code = code
        category.parent_id = parent_id
        if "name" in data and data["name"] is not None:
            category.name = self._clean_name(data["name"])
        if "category_type" in data and data["category_type"] is not None:
            category.category_type = self._clean_category_type(data["category_type"])
        if "description" in data:
            category.description = self._clean_optional_text(data["description"])
        if "sort_order" in data and data["sort_order"] is not None:
            category.sort_order = int(data["sort_order"])
        if "status" in data and data["status"] is not None:
            category.status = self._clean_status(data["status"])
        self._audit(
            context,
            "KNOWLEDGE_CATEGORY_UPDATED",
            "KNOWLEDGE_CATEGORY",
            category,
            before,
        )
        self.session.commit()
        return self._category_to_dict(category)

    def delete_category(self, context: AccessContext, category_id: str) -> None:
        category = self._require_category(context, category_id)
        if self.categories.count_documents(context.tenant_id, category.id):
            raise conflict("KNOWLEDGE_CATEGORY_HAS_DOCUMENTS", "请先移走分类下的文档")
        if self.categories.count_children(context.tenant_id, category.id):
            raise conflict("KNOWLEDGE_CATEGORY_HAS_CHILDREN", "请先删除子分类")
        before = self._category_public_dict(category)
        self._audit(
            context,
            "KNOWLEDGE_CATEGORY_DELETED",
            "KNOWLEDGE_CATEGORY",
            category,
            before,
        )
        self.categories.delete(category)
        self.session.commit()

    def validate_classification(
        self, context: AccessContext, classification: Any
    ) -> ValidatedClassification:
        data = self._payload_dict(classification)
        space_id = data.get("knowledge_space_id")
        department_id = data.get("category_department_id")
        category_id = data.get("knowledge_category_id")

        if department_id and not space_id:
            raise bad_request("CLASSIFICATION_PATH_INVALID", "分类部门必须隶属于空间")
        if category_id and (not space_id or not department_id):
            raise bad_request("CLASSIFICATION_PATH_INVALID", "分类路径不完整")

        space = self._require_space(context, space_id) if space_id else None
        department = (
            self._require_department(context, department_id) if department_id else None
        )
        category = self._require_category(context, category_id) if category_id else None
        if category:
            if category.space_id != space_id or category.department_id != department_id:
                raise bad_request("CLASSIFICATION_PATH_INVALID", "分类路径不一致")
        return ValidatedClassification(space, department, category)

    def classification_to_dict(
        self, context_or_tenant_id: AccessContext | str, document: Any
    ) -> dict:
        tenant_id = (
            context_or_tenant_id.tenant_id
            if isinstance(context_or_tenant_id, AccessContext)
            else context_or_tenant_id
        )
        space = None
        department = None
        category = None
        if document.knowledge_space_id:
            space = self.spaces.get_for_tenant(tenant_id, document.knowledge_space_id)
        if document.category_department_id:
            department = self.departments.get_for_tenant(
                tenant_id, document.category_department_id
            )
        if document.knowledge_category_id:
            category = self.categories.get_for_tenant(
                tenant_id, document.knowledge_category_id
            )
        return {
            "knowledge_space_id": document.knowledge_space_id,
            "category_department_id": document.category_department_id,
            "knowledge_category_id": document.knowledge_category_id,
            "knowledge_space": self._node_to_dict(space),
            "category_department": self._node_to_dict(department),
            "knowledge_category": self._node_to_dict(category),
        }

    def _require_space(self, context: AccessContext, space_id: str) -> KnowledgeSpace:
        space = self.spaces.get_for_tenant(context.tenant_id, space_id)
        if space is None:
            raise not_found("知识库空间不存在")
        return space

    def _require_category(
        self, context: AccessContext, category_id: str
    ) -> KnowledgeCategory:
        category = self.categories.get_for_tenant(context.tenant_id, category_id)
        if category is None:
            raise not_found("知识库分类不存在")
        return category

    def _require_department(
        self, context: AccessContext, department_id: str
    ) -> Department:
        department = self.departments.get_for_tenant(context.tenant_id, department_id)
        if department is None:
            raise not_found("部门不存在")
        return department

    def _assert_valid_parent(
        self,
        context: AccessContext,
        category: KnowledgeCategory,
        parent_id: str,
        space_id: str,
        department_id: str,
    ) -> None:
        if parent_id == category.id:
            raise bad_request("KNOWLEDGE_CATEGORY_PARENT_INVALID", "上级分类不能是自身")
        parent = self._require_category(context, parent_id)
        self._assert_parent_matches_path(parent, space_id, department_id)
        current = parent
        while current.parent_id:
            if current.parent_id == category.id:
                raise bad_request(
                    "KNOWLEDGE_CATEGORY_PARENT_INVALID", "上级分类不能是其子分类"
                )
            current = self._require_category(context, current.parent_id)

    @staticmethod
    def _assert_parent_matches_path(
        parent: KnowledgeCategory, space_id: str, department_id: str
    ) -> None:
        if parent.space_id != space_id or parent.department_id != department_id:
            raise bad_request("KNOWLEDGE_CATEGORY_PARENT_INVALID", "上级分类路径不一致")

    @staticmethod
    def _payload_dict(payload: Any, *, exclude_unset: bool = False) -> dict:
        if isinstance(payload, BaseModel):
            return payload.model_dump(exclude_unset=exclude_unset)
        if isinstance(payload, dict):
            return dict(payload)
        return {
            key: getattr(payload, key)
            for key in dir(payload)
            if not key.startswith("_") and not callable(getattr(payload, key))
        }

    @staticmethod
    def _clean_name(name: str) -> str:
        cleaned = name.strip()
        if not cleaned:
            raise bad_request("INVALID_NAME", "名称不能为空")
        return cleaned

    @staticmethod
    def _clean_code(code: str) -> str:
        cleaned = code.strip()
        if not cleaned:
            raise bad_request("INVALID_CODE", "编码不能为空")
        return cleaned

    @staticmethod
    def _clean_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @staticmethod
    def _clean_status(status: str) -> str:
        cleaned = status.strip().upper()
        if cleaned not in ACTIVE_STATUSES:
            raise bad_request("INVALID_KNOWLEDGE_STATUS", "知识库状态不支持")
        return cleaned

    @staticmethod
    def _clean_category_type(category_type: KnowledgeCategoryType | str) -> str:
        value = category_type.value if isinstance(
            category_type, KnowledgeCategoryType
        ) else str(category_type)
        value = value.strip().upper()
        if value not in {item.value for item in KnowledgeCategoryType}:
            raise bad_request("INVALID_KNOWLEDGE_CATEGORY_TYPE", "分类类型不支持")
        return value

    def _audit(
        self,
        context: AccessContext,
        action: str,
        resource_type: str,
        resource: Any,
        before: dict | None = None,
    ) -> None:
        after = self._space_public_dict(resource) if isinstance(
            resource, KnowledgeSpace
        ) else self._category_public_dict(resource)
        self.session.add(
            AuditLog(
                tenant_id=context.tenant_id,
                actor_id=context.user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource.id,
                before_snapshot=before,
                after_snapshot=after,
                request_id=current_request_id(),
            )
        )

    @staticmethod
    def _space_to_dict(space: KnowledgeSpace) -> dict:
        return {
            "id": space.id,
            "name": space.name,
            "code": space.code,
            "description": space.description,
            "status": space.status,
            "sort_order": space.sort_order,
            "created_at": space.created_at,
            "updated_at": space.updated_at,
        }

    @staticmethod
    def _category_to_dict(category: KnowledgeCategory) -> dict:
        return {
            "id": category.id,
            "space_id": category.space_id,
            "department_id": category.department_id,
            "name": category.name,
            "code": category.code,
            "category_type": category.category_type,
            "parent_id": category.parent_id,
            "description": category.description,
            "sort_order": category.sort_order,
            "status": category.status,
            "created_at": category.created_at,
            "updated_at": category.updated_at,
        }

    @staticmethod
    def _space_public_dict(space: KnowledgeSpace) -> dict:
        return {
            "id": space.id,
            "name": space.name,
            "code": space.code,
            "description": space.description,
            "status": space.status,
            "sortOrder": space.sort_order,
        }

    @staticmethod
    def _category_public_dict(category: KnowledgeCategory) -> dict:
        return {
            "id": category.id,
            "spaceId": category.space_id,
            "departmentId": category.department_id,
            "name": category.name,
            "code": category.code,
            "categoryType": str(category.category_type),
            "parentId": category.parent_id,
            "description": category.description,
            "sortOrder": category.sort_order,
            "status": category.status,
        }

    @staticmethod
    def _node_to_dict(node: Any | None) -> dict | None:
        if node is None:
            return None
        return {"id": node.id, "name": node.name, "code": node.code}

def _zero_stats() -> dict:
    return {
        "total_count": 0,
        "processing_count": 0,
        "ready_count": 0,
        "failed_count": 0,
        "unclassified_count": 0,
    }
