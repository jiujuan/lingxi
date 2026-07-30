from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column

from server.app.db.base import Base, IdMixin, TimestampMixin


class Role(IdMixin, TimestampMixin, Base):
    __tablename__ = "roles"

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), default="TENANT")
    is_builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    __table_args__ = (UniqueConstraint("tenant_id", "code"),)


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), primary_key=True
    )
    role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("roles.id"), primary_key=True, index=True
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("roles.id"), primary_key=True
    )
    permission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("permissions.id"), primary_key=True
    )

