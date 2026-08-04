"""add resumable QA split run and batch persistence

Revision ID: 0008_qa_split_long_running
Revises: 0007_adaptive_chunking
Create Date: 2026-08-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0008_qa_split_long_running"
down_revision = "0007_adaptive_chunking"
branch_labels = None
depends_on = None

RUNS_TABLE = "qa_split_runs"
BATCHES_TABLE = "qa_split_batches"
MODEL_CONFIGS_TABLE = "model_configs"
MODEL_CALL_LOGS_TABLE = "model_call_logs"
RUNNING_JOB_INDEX = "uq_qa_split_run_running_job"
TIMEOUT_COLUMNS = (
    "connect_timeout_ms",
    "write_timeout_ms",
    "read_idle_timeout_ms",
    "overall_timeout_ms",
)
MODEL_CALL_LOG_COLUMNS = (
    "batch_id",
    "batch_index",
    "retry_count",
    "split_depth",
    "input_char_count",
    "estimated_input_tokens",
    "output_char_count",
    "estimated_output_tokens",
    "timeout_phase",
    "endpoint",
    "model_name_snapshot",
)


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    if not _has_table(inspector, table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _create_run_table(inspector: sa.Inspector) -> None:
    if _has_table(inspector, RUNS_TABLE):
        return
    op.create_table(
        RUNS_TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("import_jobs.id"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id"),
            nullable=False,
        ),
        sa.Column("task_run_id", sa.String(36), sa.ForeignKey("task_runs.id")),
        sa.Column(
            "model_config_id",
            sa.String(36),
            sa.ForeignKey("model_configs.id"),
            nullable=False,
        ),
        sa.Column(
            "provider_id",
            sa.String(36),
            sa.ForeignKey("model_providers.id"),
            nullable=False,
        ),
        sa.Column("model_name", sa.String(160), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=False),
        sa.Column("chunk_generation_hash", sa.String(128), nullable=False),
        sa.Column(
            "status",
            sa.String(40),
            nullable=False,
            server_default="CREATED",
        ),
        sa.Column("batch_count", sa.Integer(), nullable=False),
        sa.Column(
            "completed_batch_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("error_code", sa.String(120)),
        sa.Column("error_message", sa.Text()),
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
        sa.CheckConstraint("batch_count >= 0", name="ck_qa_split_runs_batch_count"),
        sa.CheckConstraint(
            "completed_batch_count >= 0",
            name="ck_qa_split_runs_completed_batch_count",
        ),
        sa.CheckConstraint(
            "completed_batch_count <= batch_count",
            name="ck_qa_split_runs_completed_not_greater_than_total",
        ),
    )


def _create_batch_table(inspector: sa.Inspector) -> None:
    if _has_table(inspector, BATCHES_TABLE):
        return
    op.create_table(
        BATCHES_TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("qa_split_runs.id"),
            nullable=False,
        ),
        sa.Column("batch_index", sa.String(80), nullable=False),
        sa.Column(
            "parent_batch_id",
            sa.String(36),
            sa.ForeignKey("qa_split_batches.id"),
        ),
        sa.Column(
            "split_depth",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("chunk_indexes", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(128), nullable=False),
        sa.Column("estimated_input_tokens", sa.Integer(), nullable=False),
        sa.Column("reserved_output_tokens", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(40),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("result_payload", sa.JSON()),
        sa.Column("result_hash", sa.String(128)),
        sa.Column("error_code", sa.String(120)),
        sa.Column("error_message", sa.Text()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("timeout_phase", sa.String(40)),
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
        sa.UniqueConstraint(
            "run_id",
            "batch_index",
            name="uq_qa_split_batches_run_batch_index",
        ),
        sa.CheckConstraint(
            "split_depth >= 0",
            name="ck_qa_split_batches_split_depth",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_qa_split_batches_attempt_count",
        ),
        sa.CheckConstraint(
            "estimated_input_tokens >= 0",
            name="ck_qa_split_batches_estimated_input_tokens",
        ),
        sa.CheckConstraint(
            "reserved_output_tokens >= 0",
            name="ck_qa_split_batches_reserved_output_tokens",
        ),
    )


def _add_timeout_columns(inspector: sa.Inspector) -> None:
    columns = _column_names(inspector, MODEL_CONFIGS_TABLE)
    additions = [
        sa.Column(column_name, sa.Integer())
        for column_name in TIMEOUT_COLUMNS
        if column_name not in columns
    ]
    if not additions:
        return
    with op.batch_alter_table(MODEL_CONFIGS_TABLE) as batch_op:
        for column in additions:
            batch_op.add_column(column)


def _add_model_call_log_columns(inspector: sa.Inspector) -> None:
    columns = _column_names(inspector, MODEL_CALL_LOGS_TABLE)
    additions: list[sa.Column[object]] = []
    if "batch_id" not in columns:
        additions.append(sa.Column("batch_id", sa.String(36)))
    if "batch_index" not in columns:
        additions.append(sa.Column("batch_index", sa.String(80)))
    if "retry_count" not in columns:
        additions.append(
            sa.Column(
                "retry_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
    if "split_depth" not in columns:
        additions.append(
            sa.Column(
                "split_depth",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
    if "input_char_count" not in columns:
        additions.append(sa.Column("input_char_count", sa.Integer()))
    if "estimated_input_tokens" not in columns:
        additions.append(sa.Column("estimated_input_tokens", sa.Integer()))
    if "output_char_count" not in columns:
        additions.append(sa.Column("output_char_count", sa.Integer()))
    if "estimated_output_tokens" not in columns:
        additions.append(sa.Column("estimated_output_tokens", sa.Integer()))
    if "timeout_phase" not in columns:
        additions.append(sa.Column("timeout_phase", sa.String(40)))
    if "endpoint" not in columns:
        additions.append(sa.Column("endpoint", sa.Text()))
    if "model_name_snapshot" not in columns:
        additions.append(sa.Column("model_name_snapshot", sa.String(160)))
    if not additions:
        return
    with op.batch_alter_table(MODEL_CALL_LOGS_TABLE) as batch_op:
        for column in additions:
            batch_op.add_column(column)


def _create_postgresql_running_job_index(bind: sa.Connection) -> None:
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {RUNNING_JOB_INDEX}
        ON {RUNS_TABLE}(job_id)
        WHERE status IN ('CREATED', 'RUNNING')
        """
    )


def _drop_columns_if_present(table_name: str, column_names: tuple[str, ...]) -> None:
    inspector = sa.inspect(op.get_bind())
    existing_columns = _column_names(inspector, table_name)
    removable = [
        column_name for column_name in column_names if column_name in existing_columns
    ]
    if not removable:
        return
    with op.batch_alter_table(table_name) as batch_op:
        for column_name in removable:
            batch_op.drop_column(column_name)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _create_run_table(inspector)
    _create_batch_table(sa.inspect(bind))
    _add_timeout_columns(sa.inspect(bind))
    _add_model_call_log_columns(sa.inspect(bind))
    _create_postgresql_running_job_index(bind)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if bind.dialect.name == "postgresql" and _has_table(inspector, RUNS_TABLE):
        op.execute(f"DROP INDEX IF EXISTS {RUNNING_JOB_INDEX}")
    if _has_table(inspector, BATCHES_TABLE):
        op.drop_table(BATCHES_TABLE)
    if _has_table(sa.inspect(bind), RUNS_TABLE):
        op.drop_table(RUNS_TABLE)
    _drop_columns_if_present(MODEL_CALL_LOGS_TABLE, MODEL_CALL_LOG_COLUMNS)
    _drop_columns_if_present(MODEL_CONFIGS_TABLE, TIMEOUT_COLUMNS)
