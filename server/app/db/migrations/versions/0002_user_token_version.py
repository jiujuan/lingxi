"""add users.token_version for JWT revocation

Revision ID: 0002_user_token_version
Revises: 0001_identity_documents_core
Create Date: 2026-07-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_user_token_version"
down_revision = "0001_identity_documents_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 builds the schema with Base.metadata.create_all() from the CURRENT
    # models, so by the time this migration runs `users` may already carry
    # token_version (fresh databases always do). Every add-column migration in
    # this chain must therefore be idempotent.
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("users")}
    if "token_version" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "token_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("users")}
    if "token_version" in columns:
        op.drop_column("users", "token_version")
