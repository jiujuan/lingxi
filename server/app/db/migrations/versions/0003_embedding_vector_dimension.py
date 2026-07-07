"""align qa_pairs.question_embedding to the configured vector dimension

Revision ID: 0003_embedding_vector_dimension
Revises: 0002_user_token_version
Create Date: 2026-07-08
"""
from alembic import op
from sqlalchemy import text

from server.app.core.config import settings

revision = "0003_embedding_vector_dimension"
down_revision = "0002_user_token_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Alter the pgvector column to EMBEDDING_VECTOR_DIMENSION when it differs.

    The column dimension is configuration-driven (settings, default 1024);
    0001 creates fresh databases at the configured dimension already, so this
    migration only touches databases created under a different setting.
    Idempotent: a matching column is left alone. If the table already holds
    vectors of the old dimension, the ALTER fails loudly — that is correct:
    vectors from a different dimension/model cannot be cast and must be
    re-embedded (clear question_embedding or re-run the embedding stage).
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    dimension = int(settings.embedding_vector_dimension)
    current = bind.execute(
        text(
            """
            SELECT format_type(atttypid, atttypmod)
            FROM pg_attribute
            WHERE attrelid = 'qa_pairs'::regclass
              AND attname = 'question_embedding'
            """
        )
    ).scalar()
    if current == f"vector({dimension})":
        return
    # ALTER TYPE rebuilds the dependent HNSW index automatically.
    op.execute(
        f"ALTER TABLE qa_pairs ALTER COLUMN question_embedding TYPE vector({dimension})"
    )


def downgrade() -> None:
    # The dimension is configuration-driven; there is no fixed prior value to
    # restore. Re-run upgrade under the desired EMBEDDING_VECTOR_DIMENSION.
    pass
