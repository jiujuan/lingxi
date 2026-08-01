"""Task 20 integration coverage for the adaptive hierarchical retrieval pipeline."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select


class _WordCounter:
    name = "task20-word-counter"
    version = "1.0"

    def count(self, text: str) -> int:
        return len(text.split())

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        words = text.split()
        return [" ".join(words[index : index + limit]) for index in range(0, len(words), limit)]


def _employee_context(identity):
    from server.app.core.permissions import AccessContext

    return AccessContext(
        tenant_id=identity["tenant"].id,
        user_id=identity["users"]["employee"].id,
        department_id=identity["departments"]["support"].id,
        department_ids=[identity["departments"]["support"].id],
        role_ids=[identity["roles"]["employee"].id],
        permissions={"DOCUMENT_READ"},
    )


def _private_department_context(identity):
    from server.app.core.permissions import AccessContext

    return AccessContext(
        tenant_id=identity["tenant"].id,
        user_id="task20-no-access-user",
        department_id=identity["departments"]["private"].id,
        department_ids=[identity["departments"]["private"].id],
        role_ids=[],
        permissions={"DOCUMENT_READ"},
    )


def _other_tenant_context():
    from server.app.core.permissions import AccessContext

    return AccessContext(
        tenant_id=f"task20-other-tenant-{uuid4().hex}",
        user_id="task20-cross-tenant-user",
        department_id=None,
        role_ids=[],
        permissions={"DOCUMENT_READ"},
    )


def _postgres_url() -> str | None:
    """Only opt in to an explicitly supplied PostgreSQL integration database."""
    url = os.getenv("LINGXI_TEST_POSTGRES_URL")
    if not url:
        return None
    from sqlalchemy.engine import make_url

    return url if make_url(url).get_backend_name() == "postgresql" else None


def test_adaptive_pipeline_retrieves_skipped_child_with_hydration_rbac_and_legacy_fallback(tmp_path, monkeypatch):
    """A raw Child fact stays citable after strict QA intentionally skips it."""
    from server.app.core.retrieval_config import get_retrieval_config
    from server.app.models.document import (
        Document,
        DocumentAccessRule,
        DocumentAccessSubjectType,
        DocumentStatus,
    )
    from server.app.models.qa_pair import DocumentChunk, QaPair
    from server.app.repositories.retrieval_repo import RetrievalRepository
    from server.app.services.document_parse_service import DocumentParseService
    from server.app.services.embedding_service import EmbeddingService
    from server.app.services.prompt_service import PromptService
    from server.app.services.qa_split_service import QaSplitService
    from server.app.services.retrieval_service import RetrievalService
    from server.tests.test_embedding_task import (
        _RecordingEmbeddingAdapter,
        add_default_embedding_model,
    )
    from server.tests.test_parse_document_task import (
        _parse_chunker,
        _parse_policy,
        build_parse_session,
        create_uploaded_job,
    )
    from server.tests.test_qa_split_task import _strict_qa_payload, add_default_qa_model

    session, identity, storage = build_parse_session(tmp_path)
    markdown = b"""# Equipment handbook

Short operational note for support.

## Long procedure

alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron.

## Table

| component | owner |
| --- | --- |
| sensor | support |

## Code

```python
print('calibration')
```

## Image description

Image description: calibration badge KX-47 means the optical sensor must be reset before shipment.
"""
    job_id, document_id = create_uploaded_job(
        session, identity, storage, markdown, object_key="uploads/equipment.md"
    )

    parsed = DocumentParseService(
        session,
        storage=storage,
        adaptive_chunking=True,
        chunking_service=_parse_chunker(),
        chunking_policy=_parse_policy(),
    ).parse_import_job(job_id)
    assert parsed.stage == "QA_SPLITTING"

    active_chunks = session.scalars(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id, DocumentChunk.status == "ACTIVE")
        .order_by(DocumentChunk.chunk_level, DocumentChunk.chunk_index)
    ).all()
    parents = [chunk for chunk in active_chunks if chunk.chunk_level == "PARENT"]
    children = [chunk for chunk in active_chunks if chunk.chunk_level == "CHILD"]
    target = next(
        chunk for chunk in children if chunk.content == "eta theta iota"
    )
    qa_source = next(
        chunk for chunk in children if chunk.content == "Short operational note"
    )
    assert parents and all(child.parent_chunk_id in {parent.id for parent in parents} for child in children)

    strict_payload = _strict_qa_payload(
        items=[
            {
                "question": "Which team owns the routine support note?",
                "answer": qa_source.content,
                "quote": qa_source.content,
                "pageNo": qa_source.page_start or qa_source.page_no or 1,
                "chunkIndex": qa_source.chunk_index,
            }
        ],
        covered=[qa_source.chunk_index],
        skipped=[
            {"chunkIndex": chunk.chunk_index, "reason": "No standalone QA needed."}
            for chunk in children
            if chunk.id != qa_source.id
        ],
    )
    add_default_qa_model(session, identity["tenant"].id, strict_payload)
    qa_result = QaSplitService(session).split_import_job(job_id)
    assert qa_result.stage == "EMBEDDING"
    qa_pairs = session.scalars(
        select(QaPair).where(QaPair.document_id == document_id)
    ).all()
    assert [pair.chunk_id for pair in qa_pairs] == [qa_source.id]
    assert target.id not in {pair.chunk_id for pair in qa_pairs}

    add_default_embedding_model(session, identity["tenant"].id, expected_dimension=4)
    embedding_adapter = _RecordingEmbeddingAdapter()
    embedded = EmbeddingService(
        session,
        provider_factory=lambda *_args, **_kwargs: embedding_adapter,
        chunk_indexing_enabled=True,
    ).embed_import_job(job_id)
    session.expire_all()
    assert embedded.status == "COMPLETED"
    assert session.get(Document, document_id).status == DocumentStatus.READY
    persisted_children = session.scalars(
        select(DocumentChunk).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.chunk_level == "CHILD",
            DocumentChunk.status == "ACTIVE",
        )
    ).all()
    assert all(chunk.embedding is not None for chunk in persisted_children)
    assert all(parent.embedding is None for parent in parents)

    session.add(
        DocumentAccessRule(
            tenant_id=identity["tenant"].id,
            document_id=document_id,
            subject_type=DocumentAccessSubjectType.DEPARTMENT,
            subject_id=identity["departments"]["support"].id,
        )
    )
    session.commit()

    config = replace(
        get_retrieval_config(),
        vector_top_k=10,
        text_top_k=10,
        final_top_k=1,
        low_confidence_threshold=-1.0,
        snapshot_max_items_per_stage=20,
    )
    hybrid = RetrievalService(
        session,
        config=config,
        provider_factory=lambda *_args, **_kwargs: embedding_adapter,
        hybrid_chunk_retrieval_enabled=True,
        parent_context_enabled=True,
    )
    result = hybrid.retrieve(_employee_context(identity), "eta theta iota")
    target_candidate = next(
        (candidate for candidate in result.candidates if candidate.chunk_id == target.id),
        None,
    )
    assert target_candidate is not None, {
        "target": (target.id, target.chunk_index, target.content, target.search_text),
        "chunkText": result.snapshot["stages"]["chunkText"],
        "chunkVector": result.snapshot["stages"]["chunkVector"],
        "candidates": [candidate.to_snapshot() for candidate in result.candidates],
    }
    assert target_candidate.evidence_id == target.id
    assert target_candidate.evidence_type == "CHUNK"
    assert any(item["chunkId"] == target.id for item in result.snapshot["stages"]["chunkText"])
    assert target_candidate._lingxi_context_segments
    assert all(segment.parent_chunk_id == target.parent_chunk_id for segment in target_candidate._lingxi_context_segments)

    prompt = PromptService(
        token_counter=_WordCounter(), context_max_tokens=500
    ).build_chat_prompt("eta theta iota", [target_candidate])
    assert f"childChunkId：{target.id}" in prompt
    assert "Supplemental context（仅补充上下文，不单独引用）" in prompt

    repository = RetrievalRepository(session)
    def all_paths(context):
        return (
            repository.search_qa_vector(context, [1.0] * 4, top_k=10),
            repository.search_qa_text(
                context, ["eta", "theta", "iota"], "eta theta iota", top_k=10
            ),
            repository.search_chunk_vector(context, [1.0] * 4, top_k=10),
            repository.search_chunk_text(
                context, ["eta", "theta", "iota"], "eta theta iota", top_k=10
            ),
        )

    assert any(all_paths(_employee_context(identity)))
    assert all(not channel for channel in all_paths(_private_department_context(identity)))
    assert all(not channel for channel in all_paths(_other_tenant_context()))

    legacy = RetrievalService(
        session,
        config=config,
        provider_factory=lambda *_args, **_kwargs: embedding_adapter,
    )
    monkeypatch.setattr(legacy.repo, "search_chunk_vector", lambda *_args, **_kwargs: pytest.fail("legacy path queried Chunk vector"))
    monkeypatch.setattr(legacy.repo, "search_chunk_text", lambda *_args, **_kwargs: pytest.fail("legacy path queried Chunk text"))
    legacy_result = legacy.retrieve(_employee_context(identity), "eta theta iota")
    assert legacy_result.snapshot["channels"] == ["qa_vector", "qa_text"]

    document = session.get(Document, document_id)
    document.status = DocumentStatus.DELETED
    document.deleted_at = datetime.now(UTC)
    session.commit()
    assert all(not channel for channel in all_paths(_employee_context(identity)))


def test_celery_wrappers_chain_eager_stages_and_retry_retryable_failures(monkeypatch):
    """Celery eager mode executes parse -> QA -> embedding and preserves retries."""
    from server.app.tasks import embedding_tasks, parse_tasks, qa_tasks
    from server.app.tasks._common import TaskOutcome
    from server.app.tasks.celery_app import celery_app

    events: list[tuple[str, str]] = []
    previous_eager = celery_app.conf.task_always_eager
    previous_eager_propagates = celery_app.conf.task_eager_propagates

    class _Session:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return False

    parse_job = SimpleNamespace(
        id="task20-job", document_id="task20-document", status="RUNNING", stage="QA_SPLITTING", error_code=None
    )
    qa_job = SimpleNamespace(
        id="task20-job", document_id="task20-document", status="RUNNING", stage="EMBEDDING", error_code=None
    )
    ready_job = SimpleNamespace(
        id="task20-job", document_id="task20-document", status="COMPLETED", stage="COMPLETED", error_code=None
    )

    monkeypatch.setattr(parse_tasks, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(qa_tasks, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(embedding_tasks, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(parse_tasks, "resolve_task_outcome", lambda *_args, **_kwargs: TaskOutcome(failed=False))
    monkeypatch.setattr(qa_tasks, "resolve_task_outcome", lambda *_args, **_kwargs: TaskOutcome(failed=False))
    monkeypatch.setattr(embedding_tasks, "resolve_task_outcome", lambda *_args, **_kwargs: TaskOutcome(failed=False))
    monkeypatch.setattr(
        parse_tasks,
        "build_document_parse_service",
        lambda _session: SimpleNamespace(
            parse_import_job=lambda _job_id: (
                events.append(("parse", _job_id)) or parse_job
            )
        ),
    )
    monkeypatch.setattr(
        qa_tasks,
        "build_qa_split_service",
        lambda _session: SimpleNamespace(
            split_import_job_for_task=lambda _job_id: (
                events.append(("qa", _job_id)) or (qa_job, "task20-qa-run")
            )
        ),
    )
    monkeypatch.setattr(
        embedding_tasks,
        "build_embedding_service",
        lambda _session: SimpleNamespace(
            embed_import_job=lambda _job_id: (
                events.append(("embedding", _job_id)) or ready_job
            )
        ),
    )

    try:
        celery_app.conf.update(
            task_always_eager=True,
            task_eager_propagates=True,
        )
        result = parse_tasks.parse_document_task.apply_async(args=["task20-job"])
        assert result.get() == {
            "jobId": "task20-job",
            "documentId": "task20-document",
            "status": "RUNNING",
            "stage": "QA_SPLITTING",
            "errorCode": None,
        }
        assert events == [
            ("parse", "task20-job"),
            ("qa", "task20-job"),
            ("embedding", "task20-job"),
        ]
        completed_job = SimpleNamespace(
            id="task20-job",
            document_id="task20-document",
            status="COMPLETED",
            stage="COMPLETED",
            error_code=None,
        )
        monkeypatch.setattr(
            parse_tasks,
            "build_document_parse_service",
            lambda _session: SimpleNamespace(
                parse_import_job=lambda _job_id: (
                    events.append(("parse-replay", _job_id)) or completed_job
                )
            ),
        )
        replay_result = parse_tasks.parse_document_task.apply_async(
            args=["task20-job"]
        )
        assert replay_result.get()["status"] == "COMPLETED"
        assert events == [
            ("parse", "task20-job"),
            ("qa", "task20-job"),
            ("embedding", "task20-job"),
            ("parse-replay", "task20-job"),
        ]

        retryable = TaskOutcome(
            failed=True, retryable=True, code="TRANSIENT", message="safe"
        )
        monkeypatch.setattr(
            parse_tasks, "resolve_task_outcome", lambda *_args, **_kwargs: retryable
        )
        task = parse_tasks.parse_document_task._get_current_object()
        monkeypatch.setattr(
            task,
            "retry",
            lambda **kwargs: (_ for _ in ()).throw(
                RuntimeError(f"retry:{kwargs['countdown']}")
            ),
        )
        task.push_request(retries=0)
        try:
            with pytest.raises(RuntimeError, match=r"retry:5\.0"):
                task.run("task20-job")
        finally:
            task.pop_request()
    finally:
        celery_app.conf.update(
            task_always_eager=previous_eager,
            task_eager_propagates=previous_eager_propagates,
        )


def test_celery_local_worker_processes_each_pipeline_stage(monkeypatch):
    """An opt-in local worker consumes parse, QA, and embedding queues once."""
    broker_url = os.getenv("LINGXI_TEST_CELERY_BROKER_URL")
    if not broker_url:
        pytest.skip(
            "requires LINGXI_TEST_CELERY_BROKER_URL for local Celery worker integration"
        )

    from celery.contrib.testing.worker import start_worker

    from server.app.tasks import embedding_tasks, parse_tasks, qa_tasks
    from server.app.tasks._common import TaskOutcome
    from server.app.tasks.celery_app import celery_app

    events: list[str] = []

    class _Session:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return False

    parse_job = SimpleNamespace(
        id="task20-worker-job",
        document_id="task20-worker-document",
        status="RUNNING",
        stage="QA_SPLITTING",
        error_code=None,
    )
    qa_job = SimpleNamespace(
        id="task20-worker-job",
        document_id="task20-worker-document",
        status="RUNNING",
        stage="EMBEDDING",
        error_code=None,
    )
    completed_job = SimpleNamespace(
        id="task20-worker-job",
        document_id="task20-worker-document",
        status="COMPLETED",
        stage="COMPLETED",
        error_code=None,
    )
    for task_module in (parse_tasks, qa_tasks, embedding_tasks):
        monkeypatch.setattr(task_module, "SessionLocal", lambda: _Session())
        monkeypatch.setattr(
            task_module,
            "resolve_task_outcome",
            lambda *_args, **_kwargs: TaskOutcome(failed=False),
        )
    monkeypatch.setattr(
        parse_tasks,
        "build_document_parse_service",
        lambda _session: SimpleNamespace(
            parse_import_job=lambda _job_id: events.append("parse") or parse_job
        ),
    )
    monkeypatch.setattr(
        qa_tasks,
        "build_qa_split_service",
        lambda _session: SimpleNamespace(
            split_import_job_for_task=lambda _job_id: events.append("qa")
            or (qa_job, "task20-worker-qa-run")
        ),
    )
    monkeypatch.setattr(
        embedding_tasks,
        "build_embedding_service",
        lambda _session: SimpleNamespace(
            embed_import_job=lambda _job_id: events.append("embedding") or completed_job
        ),
    )
    previous_config = {
        key: celery_app.conf[key]
        for key in (
            "broker_url",
            "result_backend",
            "task_always_eager",
            "task_eager_propagates",
            "task_ignore_result",
        )
    }
    try:
        celery_app.conf.update(
            broker_url=broker_url,
            result_backend="cache+memory://",
            task_always_eager=False,
            task_eager_propagates=True,
            task_ignore_result=False,
        )
        with start_worker(
            celery_app,
            pool="solo",
            concurrency=1,
            queues=["parse", "qa", "embedding"],
            perform_ping_check=False,
        ):
            result = parse_tasks.parse_document_task.apply_async(
                args=["task20-worker-job"], queue="parse"
            )
            assert result.get(timeout=15)["stage"] == "QA_SPLITTING"
            deadline = monotonic() + 15
            while len(events) < 3 and monotonic() < deadline:
                sleep(0.05)
        assert events == ["parse", "qa", "embedding"]
    finally:
        celery_app.conf.update(previous_config)


def test_postgresql_chunk_retrieval_uses_pgvector_fts_acl_filters_and_production_indexes():
    """Exercise the real PostgreSQL Chunk vector/FTS paths in an isolated schema."""
    url = _postgres_url()
    if url is None:
        pytest.skip("requires LINGXI_TEST_POSTGRES_URL for PostgreSQL integration")

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from server.app.core.config import settings
    from server.app.db.base import Base
    from server.app.models.document import (
        Document,
        DocumentAccessRule,
        DocumentAccessSubjectType,
        DocumentStatus,
    )
    from server.app.models.qa_pair import DocumentChunk
    from server.app.repositories.retrieval_repo import RetrievalRepository
    from server.app.services.seed_service import seed_identity_data

    schema = f"task20_hybrid_{uuid4().hex}"
    admin_engine = create_engine(url, pool_pre_ping=True)
    test_engine = None
    session = None
    try:
        with admin_engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        test_engine = create_engine(
            url,
            connect_args={"options": f"-csearch_path={schema},public"},
            pool_pre_ping=True,
        )
        Base.metadata.create_all(bind=test_engine, checkfirst=False)
        with test_engine.begin() as connection:
            migration_path = (
                Path(__file__).parents[1]
                / "app"
                / "db"
                / "migrations"
                / "versions"
                / "0007_adaptive_hierarchical_chunks.py"
            )
            migration_spec = spec_from_file_location(
                "task20_adaptive_hierarchical_chunks_migration", migration_path
            )
            assert migration_spec and migration_spec.loader
            migration = module_from_spec(migration_spec)
            migration_spec.loader.exec_module(migration)
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

        SessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
        session = SessionLocal()
        identity = seed_identity_data(session)
        tenant_id = identity["tenant"].id
        document = Document(
            tenant_id=tenant_id,
            title="PostgreSQL equipment guide",
            file_name="equipment.md",
            file_type="MARKDOWN",
            mime_type="text/markdown",
            file_size=1,
            object_key="task20/equipment.md",
            checksum="task20-postgres",
            status=DocumentStatus.READY,
        )
        session.add(document)
        session.flush()
        session.add(DocumentAccessRule(
            tenant_id=tenant_id,
            document_id=document.id,
            subject_type=DocumentAccessSubjectType.DEPARTMENT,
            subject_id=identity["departments"]["support"].id,
        ))
        parent = DocumentChunk(
            tenant_id=tenant_id,
            document_id=document.id,
            chunk_index=0,
            content="PostgreSQL parent equipment guidance.",
            chunk_level="PARENT",
            status="ACTIVE",
        )
        session.add(parent)
        session.flush()
        dimension = settings.embedding_vector_dimension
        title_child = DocumentChunk(
            tenant_id=tenant_id,
            document_id=document.id,
            chunk_index=1,
            title_path=["TitleKX47"],
            content="routine maintenance",
            search_text="TitleKX47 routine maintenance",
            chunk_level="CHILD",
            parent_chunk_id=parent.id,
            status="ACTIVE",
            embedding=[1.0] * dimension,
        )
        content_child = DocumentChunk(
            tenant_id=tenant_id,
            document_id=document.id,
            chunk_index=2,
            title_path=["other"],
            content="ContentKX47 calibration detail",
            search_text="other ContentKX47 calibration detail",
            chunk_level="CHILD",
            parent_chunk_id=parent.id,
            status="ACTIVE",
            embedding=[0.5] * dimension,
        )
        session.add_all([title_child, content_child])
        session.commit()

        context = _employee_context(identity)
        repository = RetrievalRepository(session)
        recorded_sql: list[tuple[str, object]] = []
        from sqlalchemy import event

        def capture(_conn, _cursor, statement, parameters, _context, _many):
            if "document_chunks" in statement and "LIMIT" in statement and not statement.lstrip().startswith("EXPLAIN"):
                recorded_sql.append((statement, parameters))

        event.listen(test_engine, "before_cursor_execute", capture)
        try:
            vector_hits = repository.search_chunk_vector(context, [1.0] * dimension, top_k=5)
            title_hits = repository.search_chunk_text(context, ["titlekx47"], "TitleKX47", top_k=5)
            content_hits = repository.search_chunk_text(context, ["contentkx47"], "ContentKX47", top_k=5)
        finally:
            event.remove(test_engine, "before_cursor_execute", capture)
        assert [chunk.id for chunk, _score in vector_hits]
        assert [chunk.id for chunk, _score in title_hits] == [title_child.id]
        assert [chunk.id for chunk, _score in content_hits] == [content_child.id]

        vector_type = session.execute(text("""
            SELECT format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :schema AND c.relname = 'document_chunks' AND a.attname = 'embedding'
        """), {"schema": schema}).scalar_one()
        assert vector_type == f"vector({dimension})"
        index_names = set(session.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE schemaname = :schema AND tablename = 'document_chunks'
        """), {"schema": schema}).scalars())
        assert {"idx_document_chunks_embedding_hnsw", "idx_document_chunks_search_vector"} <= index_names
        assert recorded_sql
        for statement, parameters in recorded_sql:
            where_position = statement.upper().index("WHERE")
            order_position = statement.upper().index("ORDER BY")
            assert where_position < order_position < statement.upper().index("LIMIT")
            assert "tenant_id" in statement
            assert "EXISTS" in statement
            plan = session.connection().exec_driver_sql("EXPLAIN " + statement, parameters).all()
            assert plan
    finally:
        if session is not None:
            session.close()
        if test_engine is not None:
            test_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
