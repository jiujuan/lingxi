from sqlalchemy import delete as sa_delete, func, select, update
from sqlalchemy.orm import Session

from server.app.models.chat import ChatSession
from server.app.models.role import Role, UserRole
from server.app.models.user import Department, User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, user: User) -> User:
        self.session.add(user)
        self.session.flush()
        return user

    def get_for_tenant(self, tenant_id: str, user_id: str) -> User | None:
        return self.session.scalar(
            select(User).where(User.tenant_id == tenant_id, User.id == user_id)
        )

    def get_by_email(self, tenant_id: str, email: str) -> User | None:
        return self.session.scalar(
            select(User).where(User.tenant_id == tenant_id, User.email == email)
        )

    def search(
        self,
        tenant_id: str,
        *,
        keyword: str | None,
        department_id: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[tuple[User, str | None]], int]:
        """Page of (user, department_name) plus the total match count."""
        conditions = [User.tenant_id == tenant_id]
        if keyword:
            pattern = f"%{keyword.strip()}%"
            conditions.append(User.name.ilike(pattern) | User.email.ilike(pattern))
        if department_id:
            conditions.append(User.department_id == department_id)
        if status:
            conditions.append(User.status == status)

        total = int(
            self.session.scalar(select(func.count(User.id)).where(*conditions)) or 0
        )
        rows = self.session.execute(
            select(User, Department.name)
            .outerjoin(Department, Department.id == User.department_id)
            .where(*conditions)
            .order_by(User.created_at.desc(), User.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [(user, department_name) for user, department_name in rows], total

    def roles_by_user(self, user_ids: list[str]) -> dict[str, list[Role]]:
        if not user_ids:
            return {}
        rows = self.session.execute(
            select(UserRole.user_id, Role)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(user_ids))
            .order_by(Role.code)
        ).all()
        grouped: dict[str, list[Role]] = {}
        for user_id, role in rows:
            grouped.setdefault(user_id, []).append(role)
        return grouped

    def replace_roles(self, user_id: str, role_ids: list[str]) -> None:
        self.session.execute(sa_delete(UserRole).where(UserRole.user_id == user_id))
        for role_id in dict.fromkeys(role_ids):
            self.session.add(UserRole(user_id=user_id, role_id=role_id))
        self.session.flush()

    def delete(self, user: User) -> None:
        # Chat sessions keep history but drop the owner reference; role links go
        # with the user.
        self.session.execute(
            update(ChatSession)
            .where(ChatSession.user_id == user.id)
            .values(user_id=None)
        )
        self.session.execute(sa_delete(UserRole).where(UserRole.user_id == user.id))
        self.session.delete(user)
        self.session.flush()
