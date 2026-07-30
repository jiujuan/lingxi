import math

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.app.core.errors import bad_request, conflict, not_found
from server.app.core.ids import current_request_id
from server.app.core.permissions import AccessContext
from server.app.models.logs import AuditLog
from server.app.models.permission import Permission
from server.app.models.role import Role
from server.app.repositories.role_repo import RoleRepository


class RoleService:
    """Tenant-scoped role management with built-in-role safeguards."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = RoleRepository(session)

    def list_roles(
        self,
        context: AccessContext,
        *,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        rows, total = self.repo.search(
            context.tenant_id,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        return {
            "data": [
                self._role_list_dict(role, user_count, permission_count)
                for role, user_count, permission_count in rows
            ],
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "totalItems": total,
                "totalPages": max(1, math.ceil(total / page_size)),
            },
        }

    def get_role(self, context: AccessContext, role_id: str) -> dict:
        role = self._require_role(context, role_id)
        permissions = self.repo.list_assigned_permissions(role.id)
        return self._role_detail_dict(role, permissions)

    def list_role_options(self, context: AccessContext) -> list[dict]:
        """Return every role in the caller's tenant for user assignment."""
        return [
            {"id": role.id, "code": role.code, "name": role.name}
            for role in self.repo.list_for_tenant(context.tenant_id)
        ]

    def list_available_permissions(self, _context: AccessContext) -> list[dict]:
        return [self._permission_dict(permission) for permission in self.repo.list_permissions()]

    def create_role(
        self,
        context: AccessContext,
        *,
        name: str,
        code: str,
        permission_ids: list[str],
    ) -> dict:
        if self.repo.get_by_code(context.tenant_id, code):
            raise conflict("ROLE_CODE_EXISTS", "该角色编码已存在")
        permissions = self._resolve_permissions(permission_ids)
        try:
            role = self.repo.add(
                Role(
                    tenant_id=context.tenant_id,
                    name=name,
                    code=code,
                    scope="TENANT",
                    is_builtin=False,
                )
            )
            self.repo.replace_permission_links(role.id, permission_ids)
            self._audit(
                context, "ROLE_CREATED", role, None, self._role_public_dict(role)
            )
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            self._raise_role_code_conflict(error)
        return self._role_detail_dict(role, permissions)

    def update_role(
        self,
        context: AccessContext,
        role_id: str,
        *,
        name: str,
        code: str,
        permission_ids: list[str],
    ) -> dict:
        role = self._require_role(context, role_id)
        self._require_mutable(role)
        before = self._role_detail_dict(
            role, self.repo.list_assigned_permissions(role.id)
        )
        existing = self.repo.get_by_code(context.tenant_id, code)
        if existing and existing.id != role.id:
            raise conflict("ROLE_CODE_EXISTS", "该角色编码已存在")
        permissions = self._resolve_permissions(permission_ids)
        try:
            role.name = name
            role.code = code
            self.repo.replace_permission_links(role.id, permission_ids)
            self._audit(
                context, "ROLE_UPDATED", role, before, self._role_public_dict(role)
            )
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            self._raise_role_code_conflict(error)
        return self._role_detail_dict(role, permissions)

    def delete_role(self, context: AccessContext, role_id: str) -> None:
        role = self._require_role(context, role_id)
        self._require_mutable(role)
        before = self._role_detail_dict(
            role, self.repo.list_assigned_permissions(role.id)
        )
        try:
            deleted = self.repo.delete_if_unassigned(role)
            if not deleted:
                self.session.rollback()
                raise conflict("ROLE_HAS_USERS", "请先解除关联用户后再删除")
            self._audit(context, "ROLE_DELETED", role, before, None)
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise conflict(
                "ROLE_HAS_USERS", "请先解除关联用户后再删除"
            ) from error

    @staticmethod
    def _raise_role_code_conflict(error: IntegrityError) -> None:
        message = str(error.orig).lower()
        constraint_name = getattr(
            getattr(error.orig, "diag", None), "constraint_name", ""
        )
        if (
            "unique constraint failed: roles.tenant_id, roles.code" in message
            or constraint_name == "roles_tenant_id_code_key"
        ):
            raise conflict("ROLE_CODE_EXISTS", "该角色编码已存在") from error
        raise error

    def _resolve_permissions(self, permission_ids: list[str]) -> list[Permission]:
        unique_ids = list(dict.fromkeys(permission_ids))
        permissions = self.repo.list_permissions_by_ids(unique_ids)
        if len(permissions) != len(unique_ids):
            raise bad_request("PERMISSION_NOT_FOUND", "包含不存在的权限")
        return permissions

    def _require_role(self, context: AccessContext, role_id: str) -> Role:
        role = self.repo.get_for_tenant(context.tenant_id, role_id)
        if role is None:
            raise not_found("角色不存在")
        return role

    @staticmethod
    def _require_mutable(role: Role) -> None:
        if role.is_builtin:
            raise bad_request("BUILTIN_ROLE_PROTECTED", "内置角色不允许修改或删除")

    def _audit(
        self,
        context: AccessContext,
        action: str,
        role: Role,
        before: dict | None,
        after: dict | None,
    ) -> None:
        self.session.add(
            AuditLog(
                tenant_id=context.tenant_id,
                actor_id=context.user_id,
                action=action,
                resource_type="ROLE",
                resource_id=role.id,
                before_snapshot=before,
                after_snapshot=after,
                request_id=current_request_id(),
            )
        )

    def _role_detail_dict(self, role: Role, permissions: list[Permission]) -> dict:
        return {
            **self._role_list_dict(role, self.repo.user_count(role.id), len(permissions)),
            "permissions": [self._permission_dict(permission) for permission in permissions],
        }

    @staticmethod
    def _role_list_dict(role: Role, user_count: int, permission_count: int) -> dict:
        return {
            "id": role.id,
            "name": role.name,
            "code": role.code,
            "scope": role.scope,
            "isBuiltin": role.is_builtin,
            "userCount": user_count,
            "permissionCount": permission_count,
            "createdAt": role.created_at.isoformat() if role.created_at else "",
        }

    @staticmethod
    def _permission_dict(permission: Permission) -> dict:
        return {
            "id": permission.id,
            "code": permission.code,
            "module": permission.module,
            "action": permission.action,
            "description": permission.description,
        }

    @staticmethod
    def _role_public_dict(role: Role) -> dict:
        return {
            "id": role.id,
            "name": role.name,
            "code": role.code,
            "scope": role.scope,
            "isBuiltin": role.is_builtin,
        }