"""persist adaptive hierarchical searchable document chunks

Revision ID: 0007_adaptive_chunking
Revises: 0006_user_role_role_id_index
Create Date: 2026-07-31
"""
from __future__ import annotations

import hashlib
import unicodedata
from typing import Any

import sqlalchemy as sa
from alembic import op

from server.app.core.config import settings
from server.app.db.types import EmbeddingVector


revision = "0007_adaptive_chunking"
down_revision = "0006_user_role_role_id_index"
branch_labels = None
depends_on = None

TABLE_NAME = "document_chunks"
LEGACY_CHUNKER_NAME = "legacy_parser"
LEGACY_CHUNKER_VERSION = "legacy"
LEGACY_CONFIG_HASH = hashlib.sha256(
    f"{LEGACY_CHUNKER_NAME}:{LEGACY_CHUNKER_VERSION}".encode("utf-8")
).hexdigest()
EMPTY_CONTENT_HASH = hashlib.sha256(b"").hexdigest()

_BTREE_INDEXES: dict[str, list[str]] = {
    "idx_document_chunks_parent_chunk_id": ["parent_chunk_id"],
    "idx_document_chunks_tenant_document_status_level": [
        "tenant_id",
        "document_id",
        "status",
        "chunk_level",
        "chunk_index",
    ],
    "idx_document_chunks_tenant_content_hash": ["tenant_id", "content_hash"],
}


def _table_exists(inspector: sa.Inspector) -> bool:
    return TABLE_NAME in inspector.get_table_names()


def _column_names(inspector: sa.Inspector) -> set[str]:
    if not _table_exists(inspector):
        return set()
    return {column["name"] for column in inspector.get_columns(TABLE_NAME)}


def _index_names(inspector: sa.Inspector) -> set[str]:
    if not _table_exists(inspector):
        return set()
    return {index["name"] for index in inspector.get_indexes(TABLE_NAME)}


def _normalise_content(content: str | None) -> str:
    return unicodedata.normalize(
        "NFC", (content or "").replace("\r\n", "\n").replace("\r", "\n")
    ).strip()


def _content_hash(content: str | None) -> str:
    return hashlib.sha256(_normalise_content(content).encode("utf-8")).hexdigest()


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _add_columns(columns: set[str]) -> None:
    additions: list[sa.Column[Any]] = []
    if "block_type" not in columns:
        additions.append(
            sa.Column("block_type", sa.String(32), nullable=False, server_default="TEXT")
        )
    if "chunk_level" not in columns:
        additions.append(
            sa.Column("chunk_level", sa.String(16), nullable=False, server_default="CHILD")
        )
    if "parent_chunk_id" not in columns:
        additions.append(
            sa.Column(
                "parent_chunk_id",
                sa.String(36),
                sa.ForeignKey(
                    f"{TABLE_NAME}.id",
                    name="fk_document_chunks_parent_chunk_id",
                    ondelete="SET NULL",
                ),
            )
        )
    if "page_start" not in columns:
        additions.append(sa.Column("page_start", sa.Integer()))
    if "page_end" not in columns:
        additions.append(sa.Column("page_end", sa.Integer()))
    if "source_locators" not in columns:
        additions.append(sa.Column("source_locators", sa.JSON(), nullable=False, server_default="[]"))
    if "atomic_block_indexes" not in columns:
        additions.append(
            sa.Column("atomic_block_indexes", sa.JSON(), nullable=False, server_default="[]")
        )
    if "content_hash" not in columns:
        additions.append(
            sa.Column(
                "content_hash",
                sa.String(64),
                nullable=False,
                server_default=EMPTY_CONTENT_HASH,
            )
        )
    if "chunker_name" not in columns:
        additions.append(
            sa.Column(
                "chunker_name",
                sa.String(64),
                nullable=False,
                server_default=LEGACY_CHUNKER_NAME,
            )
        )
    if "chunker_version" not in columns:
        additions.append(
            sa.Column(
                "chunker_version",
                sa.String(32),
                nullable=False,
                server_default=LEGACY_CHUNKER_VERSION,
            )
        )
    if "chunker_config_hash" not in columns:
        additions.append(
            sa.Column(
                "chunker_config_hash",
                sa.String(64),
                nullable=False,
                server_default=LEGACY_CONFIG_HASH,
            )
        )
    if "embedding" not in columns:
        additions.append(
            sa.Column("embedding", EmbeddingVector(settings.embedding_vector_dimension))
        )
    if "search_text" not in columns:
        additions.append(sa.Column("search_text", sa.Text(), nullable=False, server_default=""))
    if "chunk_metadata" not in columns:
        additions.append(sa.Column("chunk_metadata", sa.JSON(), nullable=False, server_default="{}"))

    if not additions:
        return
    with op.batch_alter_table(TABLE_NAME) as batch_op:
        for column in additions:
            batch_op.add_column(column)


def _backfill_legacy_rows(bind: sa.Connection) -> None:
    chunks = sa.table(
        TABLE_NAME,
        sa.column("id", sa.String()),
        sa.column("chunk_index", sa.Integer()),
        sa.column("content", sa.Text()),
        sa.column("page_no", sa.Integer()),
        sa.column("source_locator", sa.JSON()),
        sa.column("block_type", sa.String()),
        sa.column("chunk_level", sa.String()),
        sa.column("page_start", sa.Integer()),
        sa.column("page_end", sa.Integer()),
        sa.column("source_locators", sa.JSON()),
        sa.column("atomic_block_indexes", sa.JSON()),
        sa.column("content_hash", sa.String()),
        sa.column("chunker_name", sa.String()),
        sa.column("chunker_version", sa.String()),
        sa.column("chunker_config_hash", sa.String()),
        sa.column("search_text", sa.Text()),
        sa.column("chunk_metadata", sa.JSON()),
    )
    rows = bind.execute(sa.select(chunks)).mappings()
    for row in rows:
        content = row["content"] or ""
        source_locator = row["source_locator"]
        source_locators = _json_list(row["source_locators"])
        if not source_locators and source_locator is not None:
            source_locators = [source_locator]
        atomic_indexes = _json_list(row["atomic_block_indexes"])
        if not atomic_indexes:
            atomic_indexes = [row["chunk_index"]]
        metadata = row["chunk_metadata"]
        if not isinstance(metadata, dict) or not metadata:
            metadata = {"legacy": True}
        bind.execute(
            chunks.update()
            .where(chunks.c.id == row["id"])
            .values(
                block_type=row["block_type"] or "TEXT",
                chunk_level=row["chunk_level"] or "CHILD",
                page_start=(
                    row["page_start"]
                    if row["page_start"] is not None
                    else row["page_no"]
                ),
                page_end=(
                    row["page_end"]
                    if row["page_end"] is not None
                    else row["page_no"]
                ),
                source_locators=source_locators,
                atomic_block_indexes=atomic_indexes,
                content_hash=(
                    _content_hash(content)
                    if not row["content_hash"]
                    or (
                        row["content_hash"] == EMPTY_CONTENT_HASH
                        and _normalise_content(content)
                    )
                    else row["content_hash"]
                ),
                chunker_name=row["chunker_name"] or LEGACY_CHUNKER_NAME,
                chunker_version=row["chunker_version"] or LEGACY_CHUNKER_VERSION,
                chunker_config_hash=(
                    row["chunker_config_hash"] or LEGACY_CONFIG_HASH
                ),
                search_text=row["search_text"] or content,
                chunk_metadata=metadata,
            )
        )


def _create_btree_indexes(bind: sa.Connection) -> None:
    inspector = sa.inspect(bind)
    index_names = _index_names(inspector)
    for index_name, columns in _BTREE_INDEXES.items():
        if index_name not in index_names:
            op.create_index(index_name, TABLE_NAME, columns)


def _create_postgresql_indexes(bind: sa.Connection) -> None:
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        ALTER TABLE document_chunks
        ADD COLUMN IF NOT EXISTS search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('simple', coalesce(search_text, ''))) STORED
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_document_chunks_search_vector
        ON document_chunks USING gin (search_vector)
        WHERE status = 'ACTIVE' AND deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_hnsw
        ON document_chunks USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL
          AND status = 'ACTIVE'
          AND deleted_at IS NULL
        """
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector):
        return

    _add_columns(_column_names(inspector))
    _backfill_legacy_rows(bind)
    _create_btree_indexes(bind)
    _create_postgresql_indexes(bind)


def _drop_postgresql_indexes(bind: sa.Connection) -> None:
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS idx_document_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS idx_document_chunks_search_vector")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS search_vector")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector):
        return

    _drop_postgresql_indexes(bind)
    inspector = sa.inspect(bind)
    for index_name in _BTREE_INDEXES:
        if index_name in _index_names(inspector):
            op.drop_index(index_name, table_name=TABLE_NAME)

    columns = _column_names(sa.inspect(bind))
    removable = [
        "chunk_metadata",
        "search_text",
        "embedding",
        "chunker_config_hash",
        "chunker_version",
        "chunker_name",
        "content_hash",
        "atomic_block_indexes",
        "source_locators",
        "page_end",
        "page_start",
        "parent_chunk_id",
        "chunk_level",
        "block_type",
    ]
    with op.batch_alter_table(TABLE_NAME) as batch_op:
        for column_name in removable:
            if column_name in columns:
                batch_op.drop_column(column_name)
