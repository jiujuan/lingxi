from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.app.db.base import Base


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "app"
    / "db"
    / "migrations"
    / "versions"
    / "0008_qa_split_long_running.py"
)
TIMEOUT_COLUMNS = {
    "connect_timeout_ms",
    "write_timeout_ms",
    "read_idle_timeout_ms",
    "overall_timeout_ms",
}
MODEL_CALL_LOG_COLUMNS = {
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
}


def _migration_module():
    spec = importlib.util.spec_from_file_location(
        "qa_split_long_running_migration", MIGRATION_PATH
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


def _legacy_schema(metadata: sa.MetaData) -> None:
    sa.Table("documents", metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table("import_jobs", metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table("task_runs", metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table(
        "model_providers", metadata, sa.Column("id", sa.String(36), primary_key=True)
    )
    sa.Table(
        "model_configs",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("timeout_ms", sa.Integer(), nullable=False, server_default="30000"),
    )
    sa.Table(
        "model_call_logs",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="SUCCESS"),
    )


def test_qa_split_run_and_batch_persist_with_foreign_keys_and_stable_paths():
    from server.app.models.qa_split_run import QaSplitBatch, QaSplitRun

    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        run = QaSplitRun(
            id="run-1",
            tenant_id="tenant-1",
            job_id="job-1",
            document_id="document-1",
            task_run_id="task-run-1",
            model_config_id="config-1",
            provider_id="provider-1",
            model_name="qa-model",
            prompt_version="qa-split-v1",
            chunk_generation_hash="a" * 64,
            status="RUNNING",
            batch_count=2,
        )
        root = QaSplitBatch(
            id="batch-root",
            run=run,
            batch_index="0",
            chunk_indexes=[0, 4],
            input_hash="b" * 64,
            estimated_input_tokens=120,
            reserved_output_tokens=40,
            status="SUCCESS",
            result_payload={"items": []},
        )
        child = QaSplitBatch(
            id="batch-child",
            run=run,
            batch_index="0.1",
            parent_batch_id="batch-root",
            split_depth=1,
            chunk_indexes=[4],
            input_hash="c" * 64,
            estimated_input_tokens=60,
            reserved_output_tokens=40,
            status="PENDING",
        )
        session.add_all((run, root, child))
        session.commit()
        session.expire_all()

        stored_run = session.get(QaSplitRun, "run-1")
        stored_child = session.get(QaSplitBatch, "batch-child")
        assert stored_run is not None
        assert stored_run.completed_batch_count == 0
        assert [batch.batch_index for batch in stored_run.batches] == ["0", "0.1"]
        assert stored_child is not None
        assert stored_child.parent_batch_id == "batch-root"
        assert stored_child.parent_batch is not None
        assert stored_child.parent_batch.batch_index == "0"

    foreign_keys = {foreign_key.target_fullname for foreign_key in QaSplitRun.__table__.foreign_keys}
    assert foreign_keys == {
        "documents.id",
        "import_jobs.id",
        "model_configs.id",
        "model_providers.id",
        "task_runs.id",
    }
    assert {
        foreign_key.target_fullname for foreign_key in QaSplitBatch.__table__.foreign_keys
    } == {"qa_split_runs.id", "qa_split_batches.id"}


def test_qa_split_batch_rejects_duplicate_path_and_unsafe_payload():
    from server.app.models.qa_split_run import QaSplitBatch, QaSplitRun

    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        run = QaSplitRun(
            id="run-1",
            tenant_id="tenant-1",
            job_id="job-1",
            document_id="document-1",
            model_config_id="config-1",
            provider_id="provider-1",
            model_name="qa-model",
            prompt_version="qa-split-v1",
            chunk_generation_hash="a" * 64,
            status="CREATED",
            batch_count=1,
        )
        first = QaSplitBatch(
            id="batch-1",
            run=run,
            batch_index="0",
            chunk_indexes=[0],
            input_hash="b" * 64,
            estimated_input_tokens=12,
            reserved_output_tokens=4,
            status="PENDING",
        )
        duplicate = QaSplitBatch(
            id="batch-2",
            run=run,
            batch_index="0",
            chunk_indexes=[1],
            input_hash="c" * 64,
            estimated_input_tokens=12,
            reserved_output_tokens=4,
            status="PENDING",
        )
        session.add_all((run, first, duplicate))
        with pytest.raises(IntegrityError):
            session.commit()

    with pytest.raises(ValueError, match="sensitive"):
        QaSplitBatch(
            id="unsafe",
            run_id="run-1",
            batch_index="1",
            chunk_indexes=[1],
            input_hash="d" * 64,
            estimated_input_tokens=12,
            reserved_output_tokens=4,
            status="SUCCESS",
            result_payload={"items": [{"content": "raw document body"}]},
        )

    with pytest.raises(ValueError, match="non-empty"):
        QaSplitBatch(
            id="empty",
            run_id="run-1",
            batch_index="2",
            chunk_indexes=[],
            input_hash="e" * 64,
            estimated_input_tokens=12,
            reserved_output_tokens=4,
            status="PENDING",
        )


def test_0008_upgrade_and_downgrade_are_idempotent_for_legacy_sqlite_schema():
    migration = _migration_module()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    _legacy_schema(metadata)
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO model_configs (id, timeout_ms) VALUES ('config-1', 30000)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO model_call_logs (id, status) VALUES ('log-1', 'SUCCESS')"
            )
        )
        with _migration_operations(connection):
            migration.upgrade()
        with _migration_operations(connection):
            migration.upgrade()

        inspector = sa.inspect(connection)
        assert {"qa_split_runs", "qa_split_batches"} <= set(inspector.get_table_names())
        assert TIMEOUT_COLUMNS <= {
            column["name"] for column in inspector.get_columns("model_configs")
        }
        assert MODEL_CALL_LOG_COLUMNS <= {
            column["name"] for column in inspector.get_columns("model_call_logs")
        }
        assert any(
            constraint["name"] == "uq_qa_split_batches_run_batch_index"
            for constraint in inspector.get_unique_constraints("qa_split_batches")
        )
        assert connection.execute(
            sa.text("SELECT timeout_ms FROM model_configs WHERE id = 'config-1'")
        ).scalar_one() == 30000
        assert connection.execute(
            sa.text("SELECT status FROM model_call_logs WHERE id = 'log-1'")
        ).scalar_one() == "SUCCESS"

        with _migration_operations(connection):
            migration.downgrade()

        inspector = sa.inspect(connection)
        assert "qa_split_runs" not in inspector.get_table_names()
        assert "qa_split_batches" not in inspector.get_table_names()
        assert not (
            TIMEOUT_COLUMNS
            & {column["name"] for column in inspector.get_columns("model_configs")}
        )
        assert not (
            MODEL_CALL_LOG_COLUMNS
            & {column["name"] for column in inspector.get_columns("model_call_logs")}
        )
        assert connection.execute(
            sa.text("SELECT timeout_ms FROM model_configs WHERE id = 'config-1'")
        ).scalar_one() == 30000
        assert connection.execute(
            sa.text("SELECT status FROM model_call_logs WHERE id = 'log-1'")
        ).scalar_one() == "SUCCESS"


def test_0008_upgrade_tolerates_0001_create_all_registering_run_batch_models():
    migration = _migration_module()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with engine.begin() as connection:
        with _migration_operations(connection):
            migration.upgrade()
        inspector = sa.inspect(connection)
        assert {"qa_split_runs", "qa_split_batches"} <= set(inspector.get_table_names())
        assert MODEL_CALL_LOG_COLUMNS <= {
            column["name"] for column in inspector.get_columns("model_call_logs")
        }


def test_checkpoint_resume_claims_only_batches_without_success():
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob, ImportJobStatus
    from server.app.models.model_config import ModelConfig, ModelProvider
    from server.app.models.qa_pair import DocumentChunk
    from server.app.models.qa_split_run import QaSplitRun
    from server.app.services.qa_split_batching import QaBatch, qa_batch_input_hash
    from server.app.services.qa_split_run_service import QaSplitRunService

    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        provider = ModelProvider(
            id="provider-1",
            tenant_id="tenant-1",
            provider_type="OPENAI_COMPATIBLE",
            name="Provider",
            status="ACTIVE",
        )
        model = ModelConfig(
            id="model-1",
            tenant_id="tenant-1",
            provider_id=provider.id,
            capability="QA_SPLIT",
            model_name="qa-model",
            is_default=True,
            status="ACTIVE",
        )
        document = Document(
            id="document-1",
            tenant_id="tenant-1",
            title="Run resume",
            file_name="resume.md",
            file_type="MARKDOWN",
            mime_type="text/markdown",
            file_size=1,
            object_key="resume.md",
            checksum="resume",
            status=DocumentStatus.QA_SPLITTING,
        )
        job = ImportJob(
            id="job-1",
            tenant_id="tenant-1",
            document_id=document.id,
            status=ImportJobStatus.RUNNING.value,
            stage="QA_SPLITTING",
        )
        chunks = [
            DocumentChunk(
                id="chunk-0",
                tenant_id="tenant-1",
                document_id=document.id,
                job_id=job.id,
                chunk_index=0,
                content="first fact",
                page_no=1,
            ),
            DocumentChunk(
                id="chunk-1",
                tenant_id="tenant-1",
                document_id=document.id,
                job_id=job.id,
                chunk_index=1,
                content="second fact",
                page_no=2,
            ),
        ]
        session.add_all((provider, model, document, job, *chunks))
        session.commit()

        batches = [
            QaBatch(
                batch_index=index,
                chunks=(chunk,),
                estimated_input_tokens=10,
                reserved_output_tokens=4,
                input_hash=qa_batch_input_hash([chunk]),
            )
            for index, chunk in enumerate(chunks)
        ]
        checkpoint = QaSplitRunService(session)
        run = checkpoint.get_or_create_run(
            job=job,
            document=document,
            model_config=model,
            provider=provider,
            batches=batches,
            task_run_id=None,
        )

        first = checkpoint.claim_next_pending_batch(run.id)
        assert first is not None
        assert first.batch_index == "0"
        checkpoint.save_success(
            first.id,
            [
                type(
                    "Item",
                    (),
                    {
                        "question": "What is first?",
                        "answer": "first fact",
                        "quote": "first fact",
                        "page_no": 1,
                        "chunk_index": 0,
                    },
                )()
            ],
            latency_ms=12,
        )
        session.commit()

        resumed = QaSplitRunService(session)
        pending = resumed.claim_next_pending_batch(run.id)

        assert pending is not None
        assert pending.batch_index == "1"
        assert session.get(Document, document.id).status == DocumentStatus.QA_SPLITTING
        assert session.get(ImportJob, job.id).stage == "QA_SPLITTING"

        model.model_name = "qa-model-v2"
        replacement = resumed.get_or_create_run(
            job=job,
            document=document,
            model_config=model,
            provider=provider,
            batches=batches,
            task_run_id="task-run-2",
        )
        assert replacement.id != run.id
        assert session.get(QaSplitRun, run.id).status == "CANCELLED"
        assert replacement.status == "RUNNING"
