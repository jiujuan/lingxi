"""mark built-in roles for role management

Revision ID: 0005_role_management
Revises: 0004_knowledge_classification
Create Date: 2026-07-30
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_role_management"
down_revision = "0004_knowledge_classification"
branch_labels = None
depends_on = None

BUILTIN_ROLE_CODES = ("SYSTEM_ADMIN", "KNOWLEDGE_ADMIN", "EMPLOYEE")


def _columns(inspector: sa.Inspector, table_name: str) -> set[str]:
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "is_builtin" not in _columns(inspector, "roles"):
        with op.batch_alter_table("roles") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "is_builtin",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )

    roles = sa.table(
        "roles",
        sa.column("code", sa.String()),
        sa.column("is_builtin", sa.Boolean()),
    )
    op.execute(
        roles.update()
        .where(roles.c.code.in_(BUILTIN_ROLE_CODES))
        .values(is_builtin=True)
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "is_builtin" in _columns(inspector, "roles"):
        with op.batch_alter_table("roles") as batch_op:
            batch_op.drop_column("is_builtin")
