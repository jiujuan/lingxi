"""identity and document core baseline

Revision ID: 0001_identity_documents_core
Revises:
Create Date: 2026-07-05
"""
from alembic import op

from server.app.db.base import Base

revision = "0001_identity_documents_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    Base.metadata.create_all(bind=bind)

    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_qa_pairs_embedding_hnsw
            ON qa_pairs USING hnsw (question_embedding vector_cosine_ops)
            WHERE question_embedding IS NOT NULL
              AND status = 'ACTIVE'
              AND deleted_at IS NULL
            """
        )
        op.execute(
            """
            ALTER TABLE qa_pairs
            ADD COLUMN IF NOT EXISTS search_vector tsvector
            GENERATED ALWAYS AS (to_tsvector('simple', coalesce(search_text, ''))) STORED
            """
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_qa_pairs_search_vector
            ON qa_pairs USING gin (search_vector)
            WHERE status = 'ACTIVE' AND deleted_at IS NULL
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)

