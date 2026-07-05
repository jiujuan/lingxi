from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.core.errors import unauthenticated
from server.app.core.config import settings
from server.app.core.security import (
    assert_token_current,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from server.app.models.permission import Permission
from server.app.models.role import Role, RolePermission, UserRole
from server.app.models.user import User


class AuthService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def login(self, email: str, password: str) -> dict:
        user = self.session.scalar(
            select(User).where(User.email == email.lower().strip())
        )
        if user is None or user.status != "ACTIVE":
            raise unauthenticated("邮箱或密码错误")
        if not verify_password(password, user.password_hash):
            raise unauthenticated("邮箱或密码错误")

        role_rows = self.session.execute(
            select(Role.id, Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
        ).all()
        role_ids = [row.id for row in role_rows]
        role_codes = sorted(row.code for row in role_rows)

        permissions = []
        if role_ids:
            permissions = sorted(
                self.session.scalars(
                    select(Permission.code)
                    .join(RolePermission, RolePermission.permission_id == Permission.id)
                    .where(RolePermission.role_id.in_(role_ids))
                ).all()
            )

        return {
            "accessToken": create_access_token(user.id, user.token_version),
            "refreshToken": create_refresh_token(user.id, user.token_version),
            "expiresIn": settings.access_token_expires_seconds,
            "user": {
                "id": user.id,
                "tenantId": user.tenant_id,
                "departmentId": user.department_id,
                "email": user.email,
                "name": user.name,
                "roles": role_codes,
                "permissions": permissions,
            },
        }

    def refresh(self, refresh_token: str) -> dict:
        payload = decode_token(refresh_token, expected_type="refresh")
        user_id = payload.get("sub")
        if not user_id:
            raise unauthenticated("Token 无效")

        user = self.session.get(User, user_id)
        if user is None or user.status != "ACTIVE":
            raise unauthenticated("用户不可用")
        assert_token_current(payload, user.token_version)

        role_rows = self.session.execute(
            select(Role.id, Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
        ).all()
        role_ids = [row.id for row in role_rows]
        role_codes = sorted(row.code for row in role_rows)
        permissions = []
        if role_ids:
            permissions = sorted(
                self.session.scalars(
                    select(Permission.code)
                    .join(RolePermission, RolePermission.permission_id == Permission.id)
                    .where(RolePermission.role_id.in_(role_ids))
                ).all()
            )

        return {
            "accessToken": create_access_token(user.id, user.token_version),
            "refreshToken": create_refresh_token(user.id, user.token_version),
            "expiresIn": settings.access_token_expires_seconds,
            "user": {
                "id": user.id,
                "tenantId": user.tenant_id,
                "departmentId": user.department_id,
                "email": user.email,
                "name": user.name,
                "roles": role_codes,
                "permissions": permissions,
            },
        }

    def logout(self, user_id: str) -> dict:
        """Revoke all outstanding tokens for the user by bumping token_version."""
        self.revoke_tokens(user_id)
        return {"ok": True}

    def revoke_tokens(self, user_id: str) -> None:
        """Invalidate every token issued so far (logout / password change / disable)."""
        user = self.session.get(User, user_id)
        if user is not None:
            user.token_version += 1
            self.session.commit()
