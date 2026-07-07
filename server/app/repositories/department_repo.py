from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.app.models.user import Department, User


class DepartmentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, department: Department) -> Department:
        self.session.add(department)
        self.session.flush()
        return department

    def get_for_tenant(self, tenant_id: str, department_id: str) -> Department | None:
        return self.session.scalar(
            select(Department).where(
                Department.tenant_id == tenant_id, Department.id == department_id
            )
        )

    def get_by_code(self, tenant_id: str, code: str) -> Department | None:
        return self.session.scalar(
            select(Department).where(
                Department.tenant_id == tenant_id, Department.code == code
            )
        )

    def list_for_tenant(self, tenant_id: str) -> list[Department]:
        return list(
            self.session.scalars(
                select(Department)
                .where(Department.tenant_id == tenant_id)
                .order_by(Department.created_at, Department.id)
            ).all()
        )

    def user_counts(self, tenant_id: str) -> dict[str, int]:
        rows = self.session.execute(
            select(User.department_id, func.count(User.id))
            .where(User.tenant_id == tenant_id, User.department_id.is_not(None))
            .group_by(User.department_id)
        ).all()
        return {department_id: count for department_id, count in rows}

    def count_children(self, department_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count(Department.id)).where(
                    Department.parent_id == department_id
                )
            )
            or 0
        )

    def count_users(self, department_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count(User.id)).where(User.department_id == department_id)
            )
            or 0
        )

    def delete(self, department: Department) -> None:
        self.session.delete(department)
        self.session.flush()
