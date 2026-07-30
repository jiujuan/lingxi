"""add an index for role-to-user association lookups

Revision ID: 0006_user_role_role_id_index
Revises: 0005_role_management
Create Date: 2026-07-30
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_user_role_role_id_index"
down_revision = "0005_role_management"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_user_roles_role_id"
TABLE_NAME = "user_roles"


def _has_index(inspector: sa.Inspector, index_name: str) -> bool:
    if TABLE_NAME not in inspector.get_table_names():
        return False
    return any(index["name"] == index_name for index in inspector.get_indexes(TABLE_NAME))


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not _has_index(inspector, INDEX_NAME):
        op.create_index(INDEX_NAME, TABLE_NAME, ["role_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _has_index(inspector, INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)