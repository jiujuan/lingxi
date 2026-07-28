"""add knowledge classification tables and document fields

Revision ID: 0004_knowledge_classification
Revises: 0003_embedding_vector_dimension
Create Date: 2026-07-29
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_knowledge_classification"
down_revision = "0003_embedding_vector_dimension"
branch_labels = None
depends_on = None


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _columns(inspector: sa.Inspector, table_name: str) -> set[str]:
    if not _table_exists(inspector, table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(inspector: sa.Inspector, table_name: str) -> set[str]:
    if not _table_exists(inspector, table_name):
        return set()
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _create_index_once(
    inspector: sa.Inspector,
    index_name: str,
    table_name: str,
    columns: list[str],
) -> None:
    if not _table_exists(inspector, table_name):
        return
    if index_name not in _indexes(inspector, table_name):
        op.create_index(index_name, table_name, columns)


def _drop_index_once(inspector: sa.Inspector, index_name: str, table_name: str) -> None:
    if (
        _table_exists(inspector, table_name)
        and index_name in _indexes(inspector, table_name)
    ):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    # 0001 creates the schema through Base.metadata.create_all() using the
    # current models. Fresh databases may therefore already have every table,
    # column, and index below before this migration is reached. Keep each step
    # explicitly idempotent so both fresh and existing databases can upgrade.
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "knowledge_spaces"):
        op.create_table(
            "knowledge_spaces",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("code", sa.String(80), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("status", sa.String(40), nullable=False, server_default="ACTIVE"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("deleted_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("tenant_id", "code"),
        )
        inspector = sa.inspect(bind)

    if not _table_exists(inspector, "knowledge_categories"):
        op.create_table(
            "knowledge_categories",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column(
                "space_id",
                sa.String(36),
                sa.ForeignKey("knowledge_spaces.id"),
                nullable=False,
            ),
            sa.Column(
                "department_id",
                sa.String(36),
                sa.ForeignKey("departments.id"),
                nullable=False,
            ),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("code", sa.String(80), nullable=False),
            sa.Column(
                "category_type",
                sa.String(40),
                nullable=False,
                server_default="TOPIC",
            ),
            sa.Column(
                "parent_id",
                sa.String(36),
                sa.ForeignKey("knowledge_categories.id"),
            ),
            sa.Column("description", sa.Text()),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(40), nullable=False, server_default="ACTIVE"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("deleted_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("tenant_id", "space_id", "department_id", "code"),
        )
        inspector = sa.inspect(bind)

    document_columns = _columns(inspector, "documents")
    if "documents" in inspector.get_table_names():
        if "knowledge_space_id" not in document_columns:
            op.add_column("documents", sa.Column("knowledge_space_id", sa.String(36)))
        if "category_department_id" not in document_columns:
            op.add_column(
                "documents", sa.Column("category_department_id", sa.String(36))
            )
        if "knowledge_category_id" not in document_columns:
            op.add_column(
                "documents", sa.Column("knowledge_category_id", sa.String(36))
            )
        inspector = sa.inspect(bind)

    _create_index_once(
        inspector,
        "idx_documents_tenant_space_updated",
        "documents",
        ["tenant_id", "knowledge_space_id", "updated_at"],
    )
    _create_index_once(
        inspector,
        "idx_documents_tenant_category_department_updated",
        "documents",
        ["tenant_id", "category_department_id", "updated_at"],
    )
    _create_index_once(
        inspector,
        "idx_documents_tenant_knowledge_category_updated",
        "documents",
        ["tenant_id", "knowledge_category_id", "updated_at"],
    )
    _create_index_once(
        inspector,
        "idx_knowledge_categories_tenant_space_department",
        "knowledge_categories",
        ["tenant_id", "space_id", "department_id", "sort_order"],
    )
    _create_index_once(
        inspector,
        "idx_knowledge_spaces_tenant_status",
        "knowledge_spaces",
        ["tenant_id", "status", "sort_order"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _drop_index_once(inspector, "idx_documents_tenant_space_updated", "documents")
    _drop_index_once(
        inspector, "idx_documents_tenant_category_department_updated", "documents"
    )
    _drop_index_once(
        inspector, "idx_documents_tenant_knowledge_category_updated", "documents"
    )
    _drop_index_once(
        inspector,
        "idx_knowledge_categories_tenant_space_department",
        "knowledge_categories",
    )
    _drop_index_once(
        inspector, "idx_knowledge_spaces_tenant_status", "knowledge_spaces"
    )
    inspector = sa.inspect(bind)

    document_columns = _columns(inspector, "documents")
    columns_to_drop = [
        column_name
        for column_name in (
            "knowledge_space_id",
            "category_department_id",
            "knowledge_category_id",
        )
        if column_name in document_columns
    ]
    if columns_to_drop:
        with op.batch_alter_table("documents") as batch_op:
            for column_name in columns_to_drop:
                batch_op.drop_column(column_name)
        inspector = sa.inspect(bind)

    if _table_exists(inspector, "knowledge_categories"):
        op.drop_table("knowledge_categories")
        inspector = sa.inspect(bind)
    if _table_exists(inspector, "knowledge_spaces"):
        op.drop_table("knowledge_spaces")
