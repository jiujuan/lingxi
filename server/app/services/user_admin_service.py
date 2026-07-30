import math

from sqlalchemy.orm import Session

from server.app.core.errors import bad_request, conflict, not_found
from server.app.core.ids import current_request_id
from server.app.core.permissions import AccessContext
from server.app.core.security import hash_password
from server.app.models.logs import AuditLog
from server.app.models.role import Role
from server.app.models.user import User
from server.app.repositories.department_repo import DepartmentRepository
from server.app.repositories.role_repo import RoleRepository
from server.app.repositories.user_repo import UserRepository


class UserAdminService:
    """Admin-side management of tenant users (the CRUD behind 用户管理)."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = UserRepository(session)
        self.role_repo = RoleRepository(session)
        self.department_repo = DepartmentRepository(session)

    def list_users(
        self,
        context: AccessContext,
        *,
        keyword: str | None,
        department_id: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        rows, total = self.repo.search(
            context.tenant_id,
            keyword=keyword,
            department_id=department_id,
            status=status,
            page=page,
            page_size=page_size,
        )
        roles_by_user = self.repo.roles_by_user([user.id for user, _ in rows])
        return {
            "data": [
                self._user_dict(user, department_name, roles_by_user.get(user.id, []))
                for user, department_name in rows
            ],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total,
                "total_pages": max(1, math.ceil(total / page_size)),
            },
        }

    def list_roles(self, context: AccessContext) -> list[Role]:
        return self.role_repo.list_for_tenant(context.tenant_id)

    def create_user(
        self,
        context: AccessContext,
        *,
        email: str,
        name: str,
        password: str,
        department_id: str | None,
        role_ids: list[str],
    ) -> dict:
        if self.repo.get_by_email(context.tenant_id, email):
            raise conflict("USER_EMAIL_EXISTS", "该邮箱已被使用")
        department_name = self._resolve_department_name(context, department_id)
        roles = self._resolve_roles(context, role_ids)
        user = User(
            tenant_id=context.tenant_id,
            department_id=department_id,
            email=email,
            name=name.strip(),
            password_hash=hash_password(password),
        )
        self.repo.add(user)
        self.repo.replace_roles(user.id, [role.id for role in roles])
        self._audit(context, "USER_CREATED", user, None)
        self.session.commit()
        return self._user_dict(user, department_name, roles)

    def update_user(
        self,
        context: AccessContext,
        user_id: str,
        *,
        email: str,
        name: str,
        department_id: str | None,
        role_ids: list[str],
    ) -> dict:
        user = self._require_user(context, user_id)
        before = self._public_dict(user)
        existing = self.repo.get_by_email(context.tenant_id, email)
        if existing and existing.id != user.id:
            raise conflict("USER_EMAIL_EXISTS", "该邮箱已被使用")
        department_name = self._resolve_department_name(context, department_id)
        roles = self._resolve_roles(context, role_ids)
        user.email = email
        user.name = name.strip()
        user.department_id = department_id
        self.repo.replace_roles(user.id, [role.id for role in roles])
        self._audit(context, "USER_UPDATED", user, before)
        self.session.commit()
        return self._user_dict(user, department_name, roles)

    def reset_password(
        self, context: AccessContext, user_id: str, *, password: str
    ) -> None:
        user = self._require_user(context, user_id)
        user.password_hash = hash_password(password)
        user.token_version += 1
        self._audit(context, "USER_PASSWORD_RESET", user, None)
        self.session.commit()

    def disable_user(self, context: AccessContext, user_id: str) -> dict:
        if user_id == context.user_id:
            raise bad_request("CANNOT_DISABLE_SELF", "不能禁用当前登录账号")
        user = self._require_user(context, user_id)
        before = self._public_dict(user)
        user.status = "DISABLED"
        user.token_version += 1
        self._audit(context, "USER_DISABLED", user, before)
        self.session.commit()
        return self._user_snapshot(context, user)

    def enable_user(self, context: AccessContext, user_id: str) -> dict:
        user = self._require_user(context, user_id)
        before = self._public_dict(user)
        user.status = "ACTIVE"
        self._audit(context, "USER_ENABLED", user, before)
        self.session.commit()
        return self._user_snapshot(context, user)

    def delete_user(self, context: AccessContext, user_id: str) -> None:
        if user_id == context.user_id:
            raise bad_request("CANNOT_DELETE_SELF", "不能删除当前登录账号")
        user = self._require_user(context, user_id)
        before = self._public_dict(user)
        self._audit(context, "USER_DELETED", user, before)
        self.repo.delete(user)
        self.session.commit()

    def _resolve_department_name(
        self, context: AccessContext, department_id: str | None
    ) -> str | None:
        if not department_id:
            return None
        department = self.department_repo.get_for_tenant(
            context.tenant_id, department_id
        )
        if department is None:
            raise bad_request("DEPARTMENT_NOT_FOUND", "部门不存在")
        return department.name

    def _resolve_roles(self, context: AccessContext, role_ids: list[str]) -> list[Role]:
        unique_ids = list(dict.fromkeys(role_ids))
        roles = self.role_repo.list_by_ids(context.tenant_id, unique_ids)
        if len(roles) != len(unique_ids):
            raise bad_request("ROLE_NOT_FOUND", "包含不存在的角色")
        return roles

    def _require_user(self, context: AccessContext, user_id: str) -> User:
        user = self.repo.get_for_tenant(context.tenant_id, user_id)
        if user is None:
            raise not_found("用户不存在")
        return user

    def _user_snapshot(self, context: AccessContext, user: User) -> dict:
        department_name = self._resolve_department_name(context, user.department_id)
        roles = self.repo.roles_by_user([user.id]).get(user.id, [])
        return self._user_dict(user, department_name, roles)

    def _audit(self, context: AccessContext, action: str, user: User, before) -> None:
        self.session.add(
            AuditLog(
                tenant_id=context.tenant_id,
                actor_id=context.user_id,
                action=action,
                resource_type="USER",
                resource_id=user.id,
                before_snapshot=before,
                after_snapshot=self._public_dict(user),
                request_id=current_request_id(),
            )
        )

    @staticmethod
    def _user_dict(user: User, department_name: str | None, roles: list[Role]) -> dict:
        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "status": user.status,
            "department_id": user.department_id,
            "department_name": department_name,
            "roles": [
                {"id": role.id, "code": role.code, "name": role.name} for role in roles
            ],
            "created_at": user.created_at.isoformat() if user.created_at else "",
        }

    @staticmethod
    def _public_dict(user: User) -> dict:
        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "status": user.status,
            "departmentId": user.department_id,
        }
