from sqlalchemy.orm import Session

from server.app.core.errors import bad_request, conflict, not_found
from server.app.core.ids import current_request_id
from server.app.core.permissions import AccessContext
from server.app.models.logs import AuditLog
from server.app.models.user import Department
from server.app.repositories.department_repo import DepartmentRepository


class DepartmentService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = DepartmentRepository(session)

    def list_departments(self, context: AccessContext) -> list[dict]:
        departments = self.repo.list_for_tenant(context.tenant_id)
        user_counts = self.repo.user_counts(context.tenant_id)
        return [
            self._serialize(item, user_counts.get(item.id, 0))
            for item in departments
        ]

    def create_department(
        self, context: AccessContext, *, name: str, code: str, parent_id: str | None
    ) -> dict:
        code = code.strip().upper()
        if self.repo.get_by_code(context.tenant_id, code):
            raise conflict("DEPARTMENT_CODE_EXISTS", "部门编码已存在")
        if parent_id:
            self._require_department(context, parent_id)
        department = Department(
            tenant_id=context.tenant_id,
            name=name.strip(),
            code=code,
            parent_id=parent_id,
        )
        self.repo.add(department)
        self._audit(context, "DEPARTMENT_CREATED", department, None)
        self.session.commit()
        return self._serialize(department, 0)

    def update_department(
        self,
        context: AccessContext,
        department_id: str,
        *,
        name: str,
        code: str,
        parent_id: str | None,
    ) -> dict:
        department = self._require_department(context, department_id)
        before = self._public_dict(department)
        code = code.strip().upper()
        existing = self.repo.get_by_code(context.tenant_id, code)
        if existing and existing.id != department.id:
            raise conflict("DEPARTMENT_CODE_EXISTS", "部门编码已存在")
        if parent_id:
            self._assert_valid_parent(context, department, parent_id)
        department.name = name.strip()
        department.code = code
        department.parent_id = parent_id
        self._audit(context, "DEPARTMENT_UPDATED", department, before)
        self.session.commit()
        return self._serialize(department, self.repo.count_users(department.id))

    def delete_department(self, context: AccessContext, department_id: str) -> None:
        department = self._require_department(context, department_id)
        if self.repo.count_children(department.id):
            raise conflict("DEPARTMENT_HAS_CHILDREN", "请先删除或移走子部门")
        if self.repo.count_users(department.id):
            raise conflict("DEPARTMENT_HAS_USERS", "请先移走部门下的用户")
        before = self._public_dict(department)
        self._audit(context, "DEPARTMENT_DELETED", department, before)
        self.repo.delete(department)
        self.session.commit()

    def _assert_valid_parent(
        self, context: AccessContext, department: Department, parent_id: str
    ) -> None:
        if parent_id == department.id:
            raise bad_request("DEPARTMENT_PARENT_INVALID", "上级部门不能是自身")
        # Walk up from the requested parent; hitting the department itself
        # would create a cycle.
        current = self._require_department(context, parent_id)
        while current.parent_id:
            if current.parent_id == department.id:
                raise bad_request(
                    "DEPARTMENT_PARENT_INVALID", "上级部门不能是其子部门"
                )
            current = self._require_department(context, current.parent_id)

    def _require_department(
        self, context: AccessContext, department_id: str
    ) -> Department:
        department = self.repo.get_for_tenant(context.tenant_id, department_id)
        if department is None:
            raise not_found("部门不存在")
        return department

    def _audit(
        self, context: AccessContext, action: str, department: Department, before
    ) -> None:
        self.session.add(
            AuditLog(
                tenant_id=context.tenant_id,
                actor_id=context.user_id,
                action=action,
                resource_type="DEPARTMENT",
                resource_id=department.id,
                before_snapshot=before,
                after_snapshot=self._public_dict(department),
                request_id=current_request_id(),
            )
        )

    @staticmethod
    def _serialize(department: Department, user_count: int) -> dict:
        return {
            "id": department.id,
            "name": department.name,
            "code": department.code,
            "parent_id": department.parent_id,
            "user_count": user_count,
            "created_at": (
                department.created_at.isoformat() if department.created_at else ""
            ),
        }

    @staticmethod
    def _public_dict(department: Department) -> dict:
        return {
            "id": department.id,
            "name": department.name,
            "code": department.code,
            "parentId": department.parent_id,
        }
