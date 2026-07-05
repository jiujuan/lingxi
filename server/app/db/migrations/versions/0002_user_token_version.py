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
    op.drop_column("users", "token_version")
