from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from server.app.db.base import Base, IdMixin, TimestampMixin


class Tenant(IdMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    deployment_mode: Mapped[str] = mapped_column(String(32), default="PRIVATE")
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")


class Department(IdMixin, TimestampMixin, Base):
    __tablename__ = "departments"

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("departments.id")
    )

    __table_args__ = (UniqueConstraint("tenant_id", "code"),)


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id"), nullable=False
    )
    department_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("departments.id")
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    # Bumped on logout / password change / disable to revoke all outstanding
    # tokens: a token whose "ver" claim no longer matches is rejected.
    token_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )

    __table_args__ = (UniqueConstraint("tenant_id", "email"),)

