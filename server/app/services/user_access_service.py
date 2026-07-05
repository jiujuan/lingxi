from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext
from server.app.models.user import User


class UserAccessService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def build_context_for_user(
        self,
        user: User,
        role_ids: list[str],
        permissions: set[str],
        role_codes: set[str] | None = None,
    ) -> AccessContext:
        return AccessContext(
            tenant_id=user.tenant_id,
            user_id=user.id,
            department_id=user.department_id,
            role_ids=role_ids,
            permissions=permissions,
            email=user.email,
            name=user.name,
            role_codes=role_codes or set(),
        )

