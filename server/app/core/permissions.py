from dataclasses import dataclass

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.core.errors import forbidden, unauthenticated
from server.app.core.security import assert_token_current, decode_token
from server.app.db.session import get_db
from server.app.models.role import Role, RolePermission, UserRole
from server.app.models.permission import Permission
from server.app.models.user import User


@dataclass(frozen=True)
class AccessContext:
    tenant_id: str
    user_id: str
    department_id: str | None
    role_ids: list[str]
    permissions: set[str]
    email: str = ""
    name: str = ""
    role_codes: set[str] | None = None
    department_ids: list[str] | None = None


security_scheme = HTTPBearer(auto_error=False)


def get_current_access_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> AccessContext:
    if credentials is None:
        raise unauthenticated()

    payload = decode_token(credentials.credentials, expected_type="access")
    user_id = payload.get("sub")
    if not user_id:
        raise unauthenticated("Token 无效")

    user = db.get(User, user_id)
    if user is None or user.status != "ACTIVE":
        raise unauthenticated("用户不可用")
    assert_token_current(payload, user.token_version)

    role_rows = db.execute(
        select(Role.id, Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    ).all()
    role_ids = [row.id for row in role_rows]
    role_codes = {row.code for row in role_rows}

    permissions = set()
    if role_ids:
        permission_rows = db.execute(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id.in_(role_ids))
        ).all()
        permissions = {row.code for row in permission_rows}

    return AccessContext(
        tenant_id=user.tenant_id,
        user_id=user.id,
        department_id=user.department_id,
        role_ids=role_ids,
        permissions=permissions,
        email=user.email,
        name=user.name,
        role_codes=role_codes,
    )


def require_permission(permission: str):
    def dependency(context: AccessContext = Depends(get_current_access_context)):
        if permission not in context.permissions:
            raise forbidden()
        return context

    return dependency
