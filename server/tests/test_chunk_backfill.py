from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from server.app.models.document import Document, DocumentStatus
from server.app.models.logs import TaskRun
from server.app.models.qa_pair import DocumentChunk
from server.app.services.chunking import ChunkPolicy, ChunkingService, LocalTokenCounter


def _policy(version: str = "2.0") -> ChunkPolicy:
    counter = LocalTokenCounter()
    return ChunkPolicy(
        version=version,
        tokenizer_name=counter.name,
        tokenizer_version=counter.version,
        min_tokens=1,
        target_tokens=4,
        max_tokens=8,
        overlap_tokens=0,
        parent_max_tokens=16,
    )


def _seed_document(
    session,
    tenant_id: str,
    *,
    suffix: str,
    version: str = "legacy",
    document_id: str | None = None,
) -> Document:
    document = Document(
        id=document_id,
        tenant_id=tenant_id,
        title=f"Backfill {suffix}",
        file_name=f"{suffix}.md",
        file_type="MARKDOWN",
        mime_type="text/markdown",
        file_size=100,
        object_key=f"uploads/{suffix}.md",
        checksum=f"checksum-{suffix}",
        status=DocumentStatus.READY,
    )
    session.add(document)
    session.flush()
    for index, content in enumerate((
        f"{suffix} alpha beta gamma",
        f"{suffix} delta epsilon zeta",
    )):
        session.add(
            DocumentChunk(
                tenant_id=tenant_id,
                document_id=document.id,
                chunk_index=index,
                content=content,
                page_no=index + 1,
                title_path=["Backfill", suffix],
                source_locator={"lineStart": index + 1},
                status="ACTIVE",
                chunk_level="CHILD",
                chunker_name="legacy_parser",
                chunker_version=version,
                chunker_config_hash=f"source-{version}",
                content_hash=f"{suffix}-{index}",
                search_text=content,
            )
        )
    session.commit()
    return document


def _service(session, *, version: str = "2.0", qa_rebuilder=None):
    from server.app.services.chunk_backfill_service import ChunkBackfillService

    counter = LocalTokenCounter()
    return ChunkBackfillService(
        session,
        chunking_service=ChunkingService(counter),
        chunking_policy=_policy(version),
        qa_rebuilder=qa_rebuilder,
    )


def _active_chunks(session, document_id: str):
    return list(
        session.scalars(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.status == "ACTIVE",
            )
            .order_by(DocumentChunk.chunk_level, DocumentChunk.chunk_index, DocumentChunk.id)
        )
    )


def _seed_import_job(session, document: Document):
    from server.app.models.import_job import ImportJob, ImportJobStatus

    job = ImportJob(
        tenant_id=document.tenant_id,
        document_id=document.id,
        status=ImportJobStatus.COMPLETED.value,
        stage="COMPLETED",
        progress=100,
    )
    session.add(job)
    session.commit()
    return job


def test_dry_run_reports_targets_without_writing_chunks():
    from server.app.services.chunk_backfill_service import BackfillOptions
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    document = _seed_document(session, identity["tenant"].id, suffix="dry-run")
    before = [(chunk.id, chunk.status) for chunk in _active_chunks(session, document.id)]

    result = _service(session).backfill(BackfillOptions(dry_run=True))

    assert result.targeted == 1
    assert result.rebuilt == 0
    assert result.next_cursor == document.id
    assert [(chunk.id, chunk.status) for chunk in _active_chunks(session, document.id)] == before


def test_backfill_filters_tenant_document_and_source_version():
    from server.app.services.chunk_backfill_service import BackfillOptions
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    first = _seed_document(session, identity["tenant"].id, suffix="first", version="1.0")
    second = _seed_document(session, identity["tenant"].id, suffix="second", version="0.9")
    other = _seed_document(session, "00000000-0000-0000-0000-000000000099", suffix="other", version="1.0")

    result = _service(session).backfill(
        BackfillOptions(
            tenant_id=identity["tenant"].id,
            document_id=first.id,
            from_chunker_version="1.0",
            to_chunker_version="2.0",
        )
    )

    assert result.rebuilt == 1
    assert {chunk.chunker_version for chunk in _active_chunks(session, first.id)} == {"2.0"}
    assert {chunk.chunker_version for chunk in _active_chunks(session, second.id)} == {"0.9"}
    assert {chunk.chunker_version for chunk in _active_chunks(session, other.id)} == {"1.0"}


def test_cursor_resume_and_same_config_retry_do_not_duplicate_collections():
    from server.app.services.chunk_backfill_service import BackfillOptions
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    first = _seed_document(session, identity["tenant"].id, suffix="a")
    second = _seed_document(session, identity["tenant"].id, suffix="b")
    ordered = sorted((first.id, second.id))

    first_pass = _service(session).backfill(BackfillOptions(batch_size=1))
    assert first_pass.rebuilt == 1
    assert first_pass.next_cursor == ordered[0]

    resumed = _service(session).backfill(
        BackfillOptions(batch_size=1, resume_after=first_pass.next_cursor)
    )
    assert resumed.rebuilt == 1
    assert resumed.next_cursor == ordered[1]

    row_count = session.query(DocumentChunk).filter(DocumentChunk.document_id == first.id).count()
    retry = _service(session).backfill(BackfillOptions(document_id=first.id))
    assert retry.reused == 1
    assert session.query(DocumentChunk).filter(DocumentChunk.document_id == first.id).count() == row_count


def test_old_active_collection_stays_active_when_validation_or_rebuild_fails(monkeypatch):
    from server.app.services.chunk_backfill_service import BackfillOptions, BackfillError
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    document = _seed_document(session, identity["tenant"].id, suffix="rollback")
    service = _service(session)

    def _boom(*_args, **_kwargs):
        raise BackfillError("VERIFY_FAILED", "verification failed", retryable=False)

    monkeypatch.setattr(service, "_verify_collection", _boom)
    with pytest.raises(BackfillError, match="VERIFY_FAILED"):
        service.backfill(BackfillOptions(document_id=document.id))

    session.expire_all()
    active = _active_chunks(session, document.id)
    assert {chunk.chunker_version for chunk in active} == {"legacy"}
    assert len(active) == 2


def test_backfill_failure_persists_retryable_task_run_after_rollback(monkeypatch):
    from server.app.services.chunk_backfill_service import BackfillError, BackfillOptions
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    document = _seed_document(session, identity["tenant"].id, suffix="durable-failure")
    service = _service(session)

    def _boom(*_args, **_kwargs):
        raise BackfillError("AUDIT_FAILURE", "safe failure", retryable=True)

    monkeypatch.setattr(service, "_verify_collection", _boom)

    with pytest.raises(BackfillError, match="AUDIT_FAILURE"):
        service.backfill(
            BackfillOptions(document_id=document.id, execution_id="backfill-execution-1"),
            task_type="backfill_adaptive_chunks_task",
            queue_name="maintenance",
        )

    session.expire_all()
    run = session.scalar(
        select(TaskRun).where(
            TaskRun.task_type == "backfill_adaptive_chunks_task",
            TaskRun.resource_id == document.id,
        )
    )
    assert run is not None
    assert run.queue_name == "maintenance"
    assert run.resource_type == "DOCUMENT"
    assert run.status == "FAILED"
    assert run.stage == "FAILED_RETRYABLE"
    assert run.request_id == "backfill-execution-1"
    assert run.error == {
        "code": "AUDIT_FAILURE",
        "retryable": True,
        "resumeAfter": None,
        "executionId": "backfill-execution-1",
    }


def test_backfill_error_log_never_contains_exception_text_or_document_content(monkeypatch, caplog):
    from server.app.services.chunk_backfill_service import BackfillError, BackfillOptions
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    sensitive_text = "DO-NOT-LOG-this-document-content"
    document = _seed_document(session, identity["tenant"].id, suffix=sensitive_text)
    service = _service(session)

    def _boom(*_args, **_kwargs):
        raise RuntimeError(sensitive_text)

    monkeypatch.setattr(service, "_rebuild_document", _boom)
    caplog.set_level("ERROR")

    with pytest.raises(BackfillError, match="CHUNK_BACKFILL_INTERNAL_ERROR"):
        service.backfill(
            BackfillOptions(document_id=document.id),
            task_type="backfill_adaptive_chunks_task",
        )

    assert sensitive_text not in caplog.text


def test_optional_qa_and_embedding_rebuilds_can_be_skipped_or_requested():
    from server.app.services.chunk_backfill_service import BackfillOptions
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    first = _seed_document(session, identity["tenant"].id, suffix="skip")
    calls: list[tuple[str, str]] = []
    service = _service(
        session,
        qa_rebuilder=lambda document, rebuild_embedding: calls.append(
            ("qa+embedding" if rebuild_embedding else "qa", document.id)
        ),
    )

    service.backfill(BackfillOptions(document_id=first.id))
    assert calls == []

    second = _seed_document(session, identity["tenant"].id, suffix="requested")
    service.backfill(
        BackfillOptions(
            document_id=second.id,
            rebuild_qa=True,
            rebuild_embedding=True,
        )
    )
    assert calls == [("qa+embedding", second.id)]


def test_embedding_rebuild_without_qa_fails_before_switching_active_collection():
    from server.app.services.chunk_backfill_service import BackfillError, BackfillOptions
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    document = _seed_document(session, identity["tenant"].id, suffix="embedding-requires-qa")

    with pytest.raises(BackfillError, match="CHUNK_BACKFILL_EMBEDDING_REQUIRES_QA"):
        _service(session).backfill(
            BackfillOptions(
                document_id=document.id,
                rebuild_embedding=True,
                execution_id="embedding-requires-qa",
            ),
            task_type="backfill_adaptive_chunks_task",
        )

    session.expire_all()
    assert {chunk.chunker_version for chunk in _active_chunks(session, document.id)} == {"legacy"}
    run = session.scalar(
        select(TaskRun).where(
            TaskRun.resource_id == document.id,
            TaskRun.task_type == "backfill_adaptive_chunks_task",
        )
    )
    assert run is not None
    assert run.status == "FAILED"
    assert run.stage == "FAILED_FINAL"
    assert run.error["code"] == "CHUNK_BACKFILL_EMBEDDING_REQUIRES_QA"
    assert run.error["retryable"] is False


def test_maintenance_factory_rearms_import_job_and_enqueues_qa_after_cutover(monkeypatch):
    from server.app.models.document import DocumentStatus
    from server.app.models.import_job import ImportJob, ImportJobStatus
    from server.app.services.chunk_backfill_service import BackfillOptions
    from server.app.tasks import maintenance_tasks
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    document = _seed_document(session, identity["tenant"].id, suffix="maintenance-queue")
    job = _seed_import_job(session, document)
    scheduled: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        maintenance_tasks,
        "enqueue_qa_task",
        lambda job_id, *, enqueue_embedding: scheduled.append((job_id, enqueue_embedding)),
    )

    class _Dependencies:
        @staticmethod
        def build_token_counter():
            return LocalTokenCounter()

        @staticmethod
        def build_chunk_policy(_counter):
            return _policy()

    monkeypatch.setattr(
        maintenance_tasks.ServiceDependencies,
        "from_settings",
        lambda: _Dependencies(),
    )
    service = maintenance_tasks._backfill_service(session)
    result = service.backfill(
        BackfillOptions(
            document_id=document.id,
            rebuild_qa=True,
            rebuild_embedding=True,
        ),
        task_type="backfill_adaptive_chunks_task",
    )

    session.expire_all()
    updated_job = session.get(ImportJob, job.id)
    updated_document = session.get(Document, document.id)
    assert result.rebuilt == 1
    assert {chunk.status for chunk in _active_chunks(session, document.id)} == {"ACTIVE"}
    assert scheduled == [(job.id, True)]
    assert updated_job.status == ImportJobStatus.RUNNING.value
    assert updated_job.stage == "QA_SPLITTING"
    assert updated_document.status == DocumentStatus.QA_SPLITTING


def test_maintenance_factory_marks_enqueue_failure_as_retryable_backfill_error(monkeypatch):
    from server.app.models.logs import TaskRun
    from server.app.services.chunk_backfill_service import BackfillError, BackfillOptions
    from server.app.tasks import maintenance_tasks
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    document = _seed_document(session, identity["tenant"].id, suffix="maintenance-enqueue-failure")
    _seed_import_job(session, document)
    monkeypatch.setattr(
        maintenance_tasks,
        "enqueue_qa_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("broker unavailable")),
    )

    with pytest.raises(BackfillError, match="CHUNK_BACKFILL_QA_SCHEDULE_FAILED"):
        maintenance_tasks._backfill_service(session).backfill(
            BackfillOptions(
                document_id=document.id,
                rebuild_qa=True,
                execution_id="maintenance-enqueue-failure",
            ),
            task_type="backfill_adaptive_chunks_task",
        )

    run = session.scalar(
        select(TaskRun).where(
            TaskRun.resource_id == document.id,
            TaskRun.task_type == "backfill_adaptive_chunks_task",
        )
    )
    assert run is not None
    assert run.status == "FAILED"
    assert run.stage == "FAILED_RETRYABLE"
    assert run.error["code"] == "CHUNK_BACKFILL_QA_SCHEDULE_FAILED"
    assert run.error["retryable"] is True


def test_target_version_must_match_configured_policy():
    from server.app.services.chunk_backfill_service import BackfillOptions
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    document = _seed_document(session, identity["tenant"].id, suffix="version")

    result = _service(session, version="3.0").backfill(
        BackfillOptions(document_id=document.id, to_chunker_version="3.0")
    )
    assert result.rebuilt == 1
    assert {chunk.chunker_version for chunk in _active_chunks(session, document.id)} == {"3.0"}


def test_task_run_persists_cli_operator_and_source_audit_metadata():
    from server.app.services.chunk_backfill_service import BackfillOptions
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    document = _seed_document(session, identity["tenant"].id, suffix="cli-audit")

    _service(session).backfill(
        BackfillOptions(
            document_id=document.id,
            execution_id="cli-audit-execution",
            operator_id="00000000-0000-0000-0000-000000000001",
            audit_source="cli",
            audit_reason="adaptive rollout",
        ),
        task_type="backfill_adaptive_chunks_cli",
    )

    run = session.scalar(
        select(TaskRun).where(
            TaskRun.task_type == "backfill_adaptive_chunks_cli",
            TaskRun.resource_id == document.id,
        )
    )
    assert run is not None
    assert run.request_id == "cli-audit-execution"
    assert run.error == {
        "resumeAfter": document.id,
        "executionId": "cli-audit-execution",
        "source": "cli",
        "operatorId": "00000000-0000-0000-0000-000000000001",
        "reason": "adaptive rollout",
    }


def test_execution_id_resumes_from_durable_cursor_in_a_new_session():
    from server.app.services.chunk_backfill_service import BackfillOptions
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    first = _seed_document(session, identity["tenant"].id, suffix="durable-a")
    second = _seed_document(session, identity["tenant"].id, suffix="durable-b")
    ordered = sorted((first.id, second.id))
    execution_id = "backfill-execution-resume"

    first_pass = _service(session).backfill(
        BackfillOptions(batch_size=1, execution_id=execution_id),
        task_type="backfill_adaptive_chunks_task",
    )
    assert first_pass.next_cursor == ordered[0]
    session.close()

    Session = sessionmaker(bind=session.bind, autoflush=False, autocommit=False)
    resumed_session = Session()
    try:
        resumed = _service(resumed_session).backfill(
            BackfillOptions(batch_size=1, execution_id=execution_id),
            task_type="backfill_adaptive_chunks_task",
        )
        assert resumed.rebuilt == 1
        assert resumed.next_cursor == ordered[1]
    finally:
        resumed_session.close()


def test_execution_cursor_advances_past_source_version_mismatch_across_sessions():
    from server.app.services.chunk_backfill_service import BackfillOptions
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    mismatch = _seed_document(
        session,
        identity["tenant"].id,
        suffix="mismatch",
        version="legacy",
        document_id="10000000-0000-0000-0000-000000000000",
    )
    matching = _seed_document(
        session,
        identity["tenant"].id,
        suffix="matching",
        version="expected",
        document_id="20000000-0000-0000-0000-000000000000",
    )
    options = BackfillOptions(
        batch_size=1,
        from_chunker_version="expected",
        execution_id="backfill-version-mismatch-resume",
    )
    matching_id = matching.id

    first = _service(session).backfill(
        options,
        task_type="backfill_adaptive_chunks_task",
    )
    checkpoint = session.scalar(
        select(TaskRun).where(
            TaskRun.task_type == "backfill_adaptive_chunks_task",
            TaskRun.resource_id == mismatch.id,
        )
    )
    assert first.targeted == 0
    assert first.next_cursor == mismatch.id
    assert checkpoint is not None
    assert checkpoint.status == "SUCCESS"
    assert checkpoint.error["resumeAfter"] == mismatch.id
    session.close()

    Session = sessionmaker(bind=session.bind, autoflush=False, autocommit=False)
    resumed_session = Session()
    try:
        resumed = _service(resumed_session).backfill(
            options,
            task_type="backfill_adaptive_chunks_task",
        )
        assert resumed.rebuilt == 1
        assert resumed.next_cursor == matching_id
    finally:
        resumed_session.close()


def test_explicit_resume_cursor_uses_durable_progress_to_avoid_rescheduling_qa():
    from server.app.services.chunk_backfill_service import BackfillError, BackfillOptions
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    already_scanned = _seed_document(
        session,
        identity["tenant"].id,
        suffix="already-scanned",
        document_id="10000000-0000-0000-0000-000000000000",
    )
    first = _seed_document(
        session,
        identity["tenant"].id,
        suffix="qa-succeeds",
        document_id="20000000-0000-0000-0000-000000000000",
    )
    failing = _seed_document(
        session,
        identity["tenant"].id,
        suffix="qa-fails",
        document_id="30000000-0000-0000-0000-000000000000",
    )
    scheduled: list[str] = []

    def _schedule(document, _rebuild_embedding):
        scheduled.append(document.id)
        if document.id == failing.id:
            raise BackfillError("QA_RETRY", "retry QA", retryable=True)

    options = BackfillOptions(
        resume_after=already_scanned.id,
        execution_id="backfill-explicit-resume",
        rebuild_qa=True,
    )
    service = _service(session, qa_rebuilder=_schedule)

    with pytest.raises(BackfillError, match="QA_RETRY"):
        service.backfill(options, task_type="backfill_adaptive_chunks_task")
    assert scheduled == [first.id, failing.id]

    with pytest.raises(BackfillError, match="QA_RETRY"):
        service.backfill(options, task_type="backfill_adaptive_chunks_task")
    assert scheduled == [first.id, failing.id, failing.id]


def test_retry_recovers_interrupted_follow_up_dispatch_without_rescheduling_qa(monkeypatch):
    from server.app.services.chunk_backfill_service import BackfillOptions
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    document = _seed_document(session, identity["tenant"].id, suffix="dispatch-crash")
    scheduled: list[tuple[str, bool]] = []
    options = BackfillOptions(
        document_id=document.id,
        execution_id="follow-up-dispatch-crash",
        rebuild_qa=True,
        rebuild_embedding=True,
    )
    interrupted = _service(
        session,
        qa_rebuilder=lambda scheduled_document, rebuild_embedding: scheduled.append(
            (scheduled_document.id, rebuild_embedding)
        ),
    )

    def _interrupt_after_dispatch(*_args, **_kwargs):
        raise KeyboardInterrupt("simulated process interruption")

    monkeypatch.setattr(interrupted, "_finish_task_run", _interrupt_after_dispatch)
    with pytest.raises(KeyboardInterrupt, match="simulated process interruption"):
        interrupted.backfill(options, task_type="backfill_adaptive_chunks_task")

    session.expire_all()
    first_run = session.scalar(
        select(TaskRun).where(
            TaskRun.task_type == "backfill_adaptive_chunks_task",
            TaskRun.resource_id == document.id,
            TaskRun.request_id == options.execution_id,
        )
    )
    assert scheduled == [(document.id, True)]
    assert first_run is not None
    assert first_run.status == "RUNNING"
    assert first_run.stage == "FOLLOW_UPS_SCHEDULED"
    assert first_run.error["followUp"] == {
        "qa": "SCHEDULED",
        "rebuildEmbedding": True,
        "targetConfigHash": _policy().config_hash,
    }

    resumed = _service(
        session,
        qa_rebuilder=lambda scheduled_document, rebuild_embedding: scheduled.append(
            (scheduled_document.id, rebuild_embedding)
        ),
    ).backfill(options, task_type="backfill_adaptive_chunks_task")

    session.expire_all()
    runs = list(
        session.scalars(
            select(TaskRun)
            .where(
                TaskRun.task_type == "backfill_adaptive_chunks_task",
                TaskRun.resource_id == document.id,
                TaskRun.request_id == options.execution_id,
            )
            .order_by(TaskRun.created_at, TaskRun.id)
        )
    )
    assert resumed.next_cursor == document.id
    assert scheduled == [(document.id, True)]
    assert [(run.status, run.stage) for run in runs] == [("SUCCESS", "READY")]
    assert runs[0].error["resumeAfter"] == document.id


def test_cli_requires_operator_and_passes_execution_and_audit_metadata(monkeypatch, capsys):
    from server.scripts import backfill_adaptive_chunks

    class _Settings:
        environment = "development"
        database_url = "postgresql+psycopg://user:secret@db.example:5432/lingxi"

    monkeypatch.setattr(backfill_adaptive_chunks, "settings", _Settings())
    with pytest.raises(SystemExit):
        backfill_adaptive_chunks.main([])

    captured = {}

    class _Service:
        def count_targets(self, _options, **kwargs):
            captured["count_kwargs"] = kwargs
            return 3

        def backfill(self, _options, **kwargs):
            captured["options"] = _options
            captured["kwargs"] = kwargs
            return type("Result", (), {"as_dict": lambda self: {"rebuilt": 0}})()

    monkeypatch.setattr(backfill_adaptive_chunks, "_build_service", lambda _session: _Service())
    monkeypatch.setattr(backfill_adaptive_chunks, "SessionLocal", lambda: _SessionContext())
    backfill_adaptive_chunks.main(
        [
            "--operator-id",
            "00000000-0000-0000-0000-000000000001",
            "--execution-id",
            "cli-backfill-1",
            "--reason",
            "adaptive rollout",
        ]
    )
    output = capsys.readouterr().out
    assert "db.example" in output
    assert "lingxi" in output
    assert "targetCount=3" in output
    assert "dryRun=False" in output
    assert "executionId=cli-backfill-1" in output
    assert captured["options"].execution_id == "cli-backfill-1"
    assert captured["options"].operator_id == "00000000-0000-0000-0000-000000000001"
    assert captured["options"].audit_source == "cli"
    assert captured["options"].audit_reason == "adaptive rollout"
    assert captured["kwargs"] == {
        "task_type": "backfill_adaptive_chunks_cli",
        "queue_name": "maintenance",
    }
    assert captured["count_kwargs"] == {
        "task_type": "backfill_adaptive_chunks_cli",
    }


class _SessionContext:
    def __enter__(self):
        return object()

    def __exit__(self, *_args):
        return False
