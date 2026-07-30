from sqlalchemy import delete as sa_delete, exists, func, select
from sqlalchemy.orm import Session

from server.app.models.permission import Permission
from server.app.models.role import Role, RolePermission, UserRole


class RoleRepository:
    """Persistence operations for tenant-scoped roles and their permissions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def search(
        self,
        tenant_id: str,
        *,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[tuple[Role, int, int]], int]:
        conditions = [Role.tenant_id == tenant_id]
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            conditions.append(Role.name.ilike(pattern) | Role.code.ilike(pattern))

        total = int(
            self.session.scalar(select(func.count(Role.id)).where(*conditions)) or 0
        )
        user_counts = (
            select(
                UserRole.role_id.label("role_id"),
                func.count(UserRole.user_id).label("user_count"),
            )
            .group_by(UserRole.role_id)
            .subquery()
        )
        permission_count = (
            select(func.count(RolePermission.permission_id))
            .where(RolePermission.role_id == Role.id)
            .correlate(Role)
            .scalar_subquery()
        )
        rows = self.session.execute(
            select(
                Role,
                func.coalesce(user_counts.c.user_count, 0).label("user_count"),
                permission_count.label("permission_count"),
            )
            .outerjoin(user_counts, user_counts.c.role_id == Role.id)
            .where(*conditions)
            .order_by(Role.created_at.desc(), Role.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [
            (role, int(users), int(permissions))
            for role, users, permissions in rows
        ], total

    def get_for_tenant(self, tenant_id: str, role_id: str) -> Role | None:
        return self.session.scalar(
            select(Role).where(Role.tenant_id == tenant_id, Role.id == role_id)
        )

    def get_by_code(self, tenant_id: str, code: str) -> Role | None:
        return self.session.scalar(
            select(Role).where(Role.tenant_id == tenant_id, Role.code == code)
        )

    def list_for_tenant(self, tenant_id: str) -> list[Role]:
        return list(
            self.session.scalars(
                select(Role).where(Role.tenant_id == tenant_id).order_by(Role.code)
            ).all()
        )

    def list_by_ids(self, tenant_id: str, role_ids: list[str]) -> list[Role]:
        if not role_ids:
            return []
        return list(
            self.session.scalars(
                select(Role).where(Role.tenant_id == tenant_id, Role.id.in_(role_ids))
            ).all()
        )

    def add(self, role: Role) -> Role:
        self.session.add(role)
        self.session.flush()
        return role

    def list_permissions(self) -> list[Permission]:
        return list(
            self.session.scalars(
                select(Permission).order_by(Permission.module, Permission.code)
            ).all()
        )

    def list_permissions_by_ids(self, permission_ids: list[str]) -> list[Permission]:
        if not permission_ids:
            return []
        return list(
            self.session.scalars(
                select(Permission)
                .where(Permission.id.in_(permission_ids))
                .order_by(Permission.module, Permission.code)
            ).all()
        )

    def list_assigned_permissions(self, role_id: str) -> list[Permission]:
        return list(
            self.session.scalars(
                select(Permission)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role_id)
                .order_by(Permission.module, Permission.code)
            ).all()
        )

    def replace_permission_links(self, role_id: str, permission_ids: list[str]) -> None:
        self.session.execute(
            sa_delete(RolePermission).where(RolePermission.role_id == role_id)
        )
        for permission_id in dict.fromkeys(permission_ids):
            self.session.add(
                RolePermission(role_id=role_id, permission_id=permission_id)
            )
        self.session.flush()

    def user_count(self, role_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count(UserRole.user_id)).where(UserRole.role_id == role_id)
            )
            or 0
        )

    def delete_if_unassigned(self, role: Role) -> bool:
        """Delete a role only while no user-role link exists.

        The conditional role deletion performs the association check and delete
        atomically. Callers roll back when it returns false because the
        permission-link cleanup has already been issued.
        """
        self.session.execute(
            sa_delete(RolePermission).where(RolePermission.role_id == role.id)
        )
        result = self.session.execute(
            sa_delete(Role).where(
                Role.id == role.id,
                ~exists(select(1).where(UserRole.role_id == role.id)),
            )
        )
        self.session.flush()
        return bool(result.rowcount)