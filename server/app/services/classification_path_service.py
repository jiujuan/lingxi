from __future__ import annotations

from sqlalchemy.orm import Session

from server.app.models.document import Document
from server.app.models.knowledge_category import KnowledgeCategory, KnowledgeSpace
from server.app.models.user import Department

UNCLASSIFIED_DISPLAY_PATH = "未分类"


class ClassificationPathService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def for_document(
        self,
        tenant_id: str,
        document: Document | None,
        snapshot: dict | None = None,
    ) -> dict:
        if document is None:
            return self.from_snapshot(snapshot)
        return self.build_path(
            tenant_id=tenant_id,
            space_id=document.knowledge_space_id,
            classification_department_id=document.category_department_id,
            category_id=document.knowledge_category_id,
        )

    def for_scope_filters(self, tenant_id: str, filters: dict | None) -> dict | None:
        filters = filters or {}
        space_id = _blank_to_none(filters.get("scopeSpaceId"))
        classification_department_id = _blank_to_none(
            filters.get("scopeClassificationDepartmentId")
        )
        category_id = _blank_to_none(filters.get("scopeCategoryId"))
        if not any([space_id, classification_department_id, category_id]):
            return None
        return self.build_path(
            tenant_id=tenant_id,
            space_id=space_id,
            classification_department_id=classification_department_id,
            category_id=category_id,
        )

    def for_run_snapshot(self, tenant_id: str, snapshot: dict | None) -> dict | None:
        snapshot = snapshot or {}
        raw_scope = snapshot.get("retrievalScope") or snapshot.get("retrieval_scope")
        if isinstance(raw_scope, dict):
            return self.from_snapshot({"classification": raw_scope})
        return self.for_scope_filters(tenant_id, snapshot.get("filters"))

    def from_snapshot(self, snapshot: dict | None) -> dict:
        snapshot = snapshot or {}
        raw = snapshot.get("classification") or snapshot.get("classificationPath") or {}
        if not isinstance(raw, dict):
            raw = {}
        path = {
            "space_id": _blank_to_none(raw.get("spaceId") or raw.get("space_id")),
            "space_name": _blank_to_none(raw.get("spaceName") or raw.get("space_name")),
            "classification_department_id": _blank_to_none(
                raw.get("classificationDepartmentId")
                or raw.get("classification_department_id")
                or raw.get("departmentId")
                or raw.get("department_id")
            ),
            "classification_department_name": _blank_to_none(
                raw.get("classificationDepartmentName")
                or raw.get("classification_department_name")
                or raw.get("departmentName")
                or raw.get("department_name")
            ),
            "category_id": _blank_to_none(raw.get("categoryId") or raw.get("category_id")),
            "category_name": _blank_to_none(
                raw.get("categoryName") or raw.get("category_name")
            ),
            "display_path": _blank_to_none(
                raw.get("displayPath") or raw.get("display_path")
            )
            or UNCLASSIFIED_DISPLAY_PATH,
        }
        if path["display_path"] == UNCLASSIFIED_DISPLAY_PATH:
            path["display_path"] = _display_path(path)
        return path

    def build_path(
        self,
        *,
        tenant_id: str,
        space_id: str | None,
        classification_department_id: str | None,
        category_id: str | None,
    ) -> dict:
        space_id = _blank_to_none(space_id)
        classification_department_id = _blank_to_none(classification_department_id)
        category_id = _blank_to_none(category_id)
        path = {
            "space_id": space_id,
            "space_name": self._space_name(tenant_id, space_id),
            "classification_department_id": classification_department_id,
            "classification_department_name": self._department_name(
                tenant_id, classification_department_id
            ),
            "category_id": category_id,
            "category_name": self._category_name(tenant_id, category_id),
            "display_path": UNCLASSIFIED_DISPLAY_PATH,
        }
        path["display_path"] = _display_path(path)
        return path

    def _space_name(self, tenant_id: str, space_id: str | None) -> str | None:
        if not space_id:
            return None
        space = self.session.get(KnowledgeSpace, space_id)
        if space is None or space.tenant_id != tenant_id:
            return None
        return space.name

    def _department_name(self, tenant_id: str, department_id: str | None) -> str | None:
        if not department_id:
            return None
        department = self.session.get(Department, department_id)
        if department is None or department.tenant_id != tenant_id:
            return None
        return department.name

    def _category_name(self, tenant_id: str, category_id: str | None) -> str | None:
        if not category_id:
            return None
        category = self.session.get(KnowledgeCategory, category_id)
        if category is None or category.tenant_id != tenant_id:
            return None
        return category.name


def classification_path_to_public(path: dict | None) -> dict | None:
    if path is None:
        return None
    return {
        "spaceId": path.get("space_id"),
        "spaceName": path.get("space_name"),
        "classificationDepartmentId": path.get("classification_department_id"),
        "classificationDepartmentName": path.get("classification_department_name"),
        "categoryId": path.get("category_id"),
        "categoryName": path.get("category_name"),
        "displayPath": path.get("display_path") or UNCLASSIFIED_DISPLAY_PATH,
    }


def _display_path(path: dict) -> str:
    parts = [
        path.get("space_name") or path.get("space_id"),
        path.get("classification_department_name")
        or path.get("classification_department_id"),
        path.get("category_name") or path.get("category_id"),
    ]
    parts = [str(part) for part in parts if part]
    return " / ".join(parts) if parts else UNCLASSIFIED_DISPLAY_PATH


def _blank_to_none(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None
