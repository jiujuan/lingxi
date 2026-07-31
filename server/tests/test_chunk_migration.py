from __future__ import annotations

import hashlib
import importlib.util
import json
from contextlib import contextmanager
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from server.app.core.config import settings
from server.app.db.base import Base
from server.app.models.qa_pair import DocumentChunk, QaPair


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "app"
    / "db"
    / "migrations"
    / "versions"
    / "0007_adaptive_hierarchical_chunks.py"
)
NEW_COLUMNS = {
    "block_type",
    "chunk_level",
    "parent_chunk_id",
    "page_start",
    "page_end",
    "source_locators",
    "atomic_block_indexes",
    "content_hash",
    "chunker_name",
    "chunker_version",
    "chunker_config_hash",
    "embedding",
    "search_text",
    "chunk_metadata",
}
BTREE_INDEXES = {
    "idx_document_chunks_parent_chunk_id",
    "idx_document_chunks_tenant_document_status_level",
    "idx_document_chunks_tenant_content_hash",
}


def _migration_module():
    spec = importlib.util.spec_from_file_location(
        "adaptive_hierarchical_chunks_migration", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _migration_operations(connection: sa.Connection):
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        yield


def _legacy_document_chunks_table(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        "document_chunks",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36)),
        sa.Column("job_id", sa.String(36)),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("title_path", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("page_no", sa.Integer),
        sa.Column("token_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("source_locator", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(40), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )


def _prepare_legacy_database() -> tuple[sa.Engine, set[str]]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    legacy = _legacy_document_chunks_table(metadata)
    metadata.create_all(engine)
    legacy_index = "idx_legacy_document_chunks_chunk_index"
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                f"CREATE INDEX {legacy_index} "
                "ON document_chunks (chunk_index)"
            )
        )
        connection.execute(
            legacy.insert(),
            {
                "id": "legacy-chunk",
                "tenant_id": "tenant-1",
                "document_id": "document-1",
                "job_id": "job-1",
                "chunk_index": 0,
                "title_path": ["legacy"],
                "content": "legacy body",
                "page_no": 3,
                "token_count": 2,
                "source_locator": {"legacy": True},
                "status": "ACTIVE",
            },
        )
    return engine, {column.name for column in legacy.columns}


def test_document_chunk_model_has_hierarchical_search_fields_and_safe_relationship():
    column_names = set(DocumentChunk.__table__.columns.keys())
    assert NEW_COLUMNS <= column_names
    assert DocumentChunk.__table__.c.embedding.type.dimension == (
        QaPair.__table__.c.question_embedding.type.dimension
    )
    assert DocumentChunk.__table__.c.embedding.type.dimension == (
        settings.embedding_vector_dimension
    )
    assert DocumentChunk.parent_chunk.property.lazy != "joined"
    assert DocumentChunk.parent_chunk.property.lazy != "subquery"
    assert {
        index.name for index in DocumentChunk.__table__.indexes
    } >= BTREE_INDEXES

    postgresql_ddl = str(CreateTable(DocumentChunk.__table__).compile(
        dialect=postgresql.dialect()
    ))
    assert f"vector({settings.embedding_vector_dimension})" in postgresql_ddl


def test_model_legacy_config_default_matches_migration_backfill_contract():
    migration = _migration_module()
    assert DocumentChunk.__table__.c.chunker_config_hash.server_default.arg == (
        migration.LEGACY_CONFIG_HASH
    )


def test_model_defaults_and_self_reference_persist_without_recursive_eager_loading():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        parent = DocumentChunk(
            id="parent-chunk",
            tenant_id="tenant-1",
            document_id="document-1",
            chunk_index=0,
            content="parent content",
        )
        child = DocumentChunk(
            id="child-chunk",
            tenant_id="tenant-1",
            document_id="document-1",
            chunk_index=1,
            content="child content",
            parent_chunk=parent,
        )
        session.add_all((parent, child))
        session.commit()
        session.expire_all()

        stored = session.get(DocumentChunk, "child-chunk")
        assert stored is not None
        assert stored.parent_chunk_id == "parent-chunk"
        assert stored.block_type == "TEXT"
        assert stored.chunk_level == "CHILD"
        assert stored.chunker_name == "legacy_parser"
        assert stored.parent_chunk is not None
        assert stored.parent_chunk.id == "parent-chunk"


def test_upgrade_backfills_legacy_rows_and_keeps_indexes_sqlite_compatible():
    migration = _migration_module()
    engine, legacy_columns = _prepare_legacy_database()
    with engine.begin() as connection:
        with _migration_operations(connection):
            migration.upgrade()

        inspector = sa.inspect(connection)
        columns = {column["name"] for column in inspector.get_columns("document_chunks")}
        assert legacy_columns | NEW_COLUMNS <= columns
        assert BTREE_INDEXES <= {
            index["name"] for index in inspector.get_indexes("document_chunks")
        }
        row = connection.execute(
            sa.text(
                "SELECT block_type, chunk_level, chunker_name, content_hash, "
                "source_locators, atomic_block_indexes, search_text, chunk_metadata "
                "FROM document_chunks WHERE id = 'legacy-chunk'"
            )
        ).mappings().one()

    assert row["block_type"] == "TEXT"
    assert row["chunk_level"] == "CHILD"
    assert row["chunker_name"] == "legacy_parser"
    assert row["content_hash"] == hashlib.sha256(b"legacy body").hexdigest()
    assert json.loads(row["source_locators"]) == [{"legacy": True}]
    assert json.loads(row["atomic_block_indexes"]) == [0]
    assert row["search_text"] == "legacy body"
    assert json.loads(row["chunk_metadata"]) == {"legacy": True}


def test_self_fk_and_downgrade_only_remove_adaptive_schema():
    migration = _migration_module()
    engine, legacy_columns = _prepare_legacy_database()
    with engine.begin() as connection:
        with _migration_operations(connection):
            migration.upgrade()

        foreign_keys = sa.inspect(connection).get_foreign_keys("document_chunks")
        assert any(
            foreign_key["constrained_columns"] == ["parent_chunk_id"]
            and foreign_key["referred_table"] == "document_chunks"
            for foreign_key in foreign_keys
        )
        connection.execute(
            sa.text(
                "INSERT INTO document_chunks "
                "(id, tenant_id, document_id, chunk_index, content, parent_chunk_id) "
                "VALUES ('parent', 'tenant-1', 'document-1', 1, 'parent', NULL)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO document_chunks "
                "(id, tenant_id, document_id, chunk_index, content, parent_chunk_id) "
                "VALUES ('child', 'tenant-1', 'document-1', 2, 'child', 'parent')"
            )
        )
        assert connection.execute(
            sa.text("SELECT parent_chunk_id FROM document_chunks WHERE id = 'child'")
        ).scalar_one() == "parent"

        with _migration_operations(connection):
            migration.downgrade()

        inspector = sa.inspect(connection)
        columns = {column["name"] for column in inspector.get_columns("document_chunks")}
        assert columns == legacy_columns
        indexes = {index["name"] for index in inspector.get_indexes("document_chunks")}
        assert "idx_legacy_document_chunks_chunk_index" in indexes
        assert not (BTREE_INDEXES & indexes)
        assert connection.execute(
            sa.text("SELECT content FROM document_chunks WHERE id = 'legacy-chunk'")
        ).scalar_one() == "legacy body"
