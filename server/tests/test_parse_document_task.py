from sqlalchemy import select
import pytest


def build_parse_session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from server.app.db.base import Base
    from server.app.integrations.storage.local import LocalObjectStorage
    from server.app.services.seed_service import seed_identity_data

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    identity = seed_identity_data(session)
    storage = LocalObjectStorage(tmp_path)
    return session, identity, storage


def create_uploaded_job(
    session,
    identity,
    storage,
    content: bytes,
    object_key: str = "uploads/doc.md",
):
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob, ImportJobFile, ImportJobStatus

    tenant_id = identity["tenant"].id
    storage.put_object(object_key=object_key, data=content)

    file_name = object_key.rsplit("/", 1)[-1]
    if file_name.endswith(".pdf"):
        mime_type = "application/pdf"
        file_type = "PDF"
    elif file_name.endswith(".csv"):
        mime_type = "text/csv"
        file_type = "CSV"
    else:
        mime_type = "text/markdown"
        file_type = "MARKDOWN"

    document = Document(
        tenant_id=tenant_id,
        title="Parser Guide",
        file_name=file_name,
        file_type=file_type,
        mime_type=mime_type,
        file_size=len(content),
        object_key=object_key,
        checksum="parse-checksum",
        status=DocumentStatus.PARSING,
    )
    session.add(document)
    session.flush()

    job = ImportJob(
        tenant_id=tenant_id,
        document_id=document.id,
        status=ImportJobStatus.RUNNING.value,
        stage="PARSING",
        progress=10,
    )
    session.add(job)
    session.flush()
    session.add(
        ImportJobFile(
            tenant_id=tenant_id,
            job_id=job.id,
            object_key=object_key,
            file_name=file_name,
            mime_type=mime_type,
            file_size=len(content),
            checksum="parse-checksum",
        )
    )
    session.commit()
    return job.id, document.id


def test_lightweight_parser_splits_markdown_into_blocks():
    from server.app.integrations.parsers.base import ParseRequest, ParseSource
    from server.app.integrations.parsers.lightweight import LightweightParser

    parser = LightweightParser()
    parsed = parser.parse(
        ParseRequest(
            source=ParseSource(
                file_name="sample.md",
                mime_type="text/markdown",
                content=b"# Title\n\nFirst paragraph.\n\n## Step\n\nSecond paragraph.",
            )
        )
    )

    assert parsed.parser_name == "LIGHTWEIGHT"
    assert parsed.markdown.startswith("# Title")
    assert [block.content for block in parsed.blocks] == [
        "First paragraph.",
        "Second paragraph.",
    ]
    assert parsed.blocks[1].title_path == ["Title", "Step"]


def test_lightweight_parser_emits_markdown_structural_block_types():
    from server.app.integrations.parsers.base import ParseRequest, ParseSource
    from server.app.integrations.parsers.lightweight import LightweightParser
    from server.app.services.chunking.contracts import BlockType

    parsed = LightweightParser().parse(
        ParseRequest(
            source=ParseSource(
                file_name="structures.md",
                mime_type="text/markdown",
                content=(
                    "正文。\n\n- first\n- second\n\n> 引用。\n\n"
                    "```python\nprint('ok')\n```\n\n"
                    "| a | b |\n| --- | --- |\n| 1 | 2 |"
                ).encode(),
            )
        )
    )

    assert [block.block_type for block in parsed.blocks] == [
        BlockType.TEXT,
        BlockType.LIST,
        BlockType.QUOTE,
        BlockType.CODE,
        BlockType.TABLE,
    ]
    assert parsed.blocks[3].metadata == {
        "language": "python",
        "sourceLabel": "markdown_fence",
    }
    assert parsed.blocks[4].metadata["sourceLabel"] == "markdown_table"
    assert parsed.blocks[4].source_locator == {"lineStart": 12, "lineEnd": 14}


def test_lightweight_parser_classifies_markdown_continuations_without_false_tables():
    from server.app.integrations.parsers.base import ParseRequest, ParseSource
    from server.app.integrations.parsers.lightweight import LightweightParser
    from server.app.services.chunking.contracts import BlockType

    cases = {
        "list.md": "- first item\n  continuation text\n  - nested item",
        "quote.md": "> quoted lead\nlazy continuation",
        "not-a-table.md": "This is not a table\n--- | ---",
    }
    expected = [BlockType.LIST, BlockType.QUOTE, BlockType.TEXT]

    actual = []
    for file_name, markdown in cases.items():
        parsed = LightweightParser().parse(
            ParseRequest(
                source=ParseSource(
                    file_name=file_name,
                    mime_type="text/markdown",
                    content=markdown.encode(),
                )
            )
        )
        actual.append(parsed.blocks[0].block_type)

    assert actual == expected


def test_lightweight_parser_keeps_top_level_blocks_out_of_a_list():
    from server.app.integrations.parsers.base import ParseRequest, ParseSource
    from server.app.integrations.parsers.lightweight import LightweightParser
    from server.app.services.chunking.contracts import BlockType

    def block_types(markdown: str) -> list[BlockType]:
        parsed = LightweightParser().parse(
            ParseRequest(
                source=ParseSource(
                    file_name="list-boundaries.md",
                    mime_type="text/markdown",
                    content=markdown.encode(),
                )
            )
        )
        return [block.block_type for block in parsed.blocks]

    assert block_types("- item\n```python\nprint('top level')\n```") == [
        BlockType.LIST,
        BlockType.CODE,
    ]
    assert block_types("- item\n> top-level quote") == [
        BlockType.LIST,
        BlockType.QUOTE,
    ]
    # An indented fence belongs to the list item, so it is deliberately one
    # LIST atomic block rather than a sibling top-level CODE block.
    assert block_types("- item\n  ```python\n  print('nested')\n  ```") == [
        BlockType.LIST,
    ]


def test_parse_document_service_writes_artifact_and_chunks_idempotently(tmp_path):
    session, identity, storage = build_parse_session(tmp_path)
    job_id, document_id = create_uploaded_job(
        session,
        identity,
        storage,
        b"# Refund SOP\n\nRefund requires approval.\n\n## Invoice\n\nVoid invoice first.",
    )

    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob
    from server.app.models.qa_pair import DocumentChunk
    from server.app.models.import_job import ParseArtifact
    from server.app.services.document_parse_service import DocumentParseService

    service = DocumentParseService(session, storage=storage)
    first = service.parse_import_job(job_id)
    second = service.parse_import_job(job_id)

    assert first.status == "RUNNING"
    assert second.stage == "QA_SPLITTING"

    document = session.get(Document, document_id)
    job = session.get(ImportJob, job_id)
    chunks = session.scalars(
        select(DocumentChunk).where(DocumentChunk.document_id == document_id)
    ).all()
    artifacts = session.scalars(
        select(ParseArtifact).where(ParseArtifact.document_id == document_id)
    ).all()

    assert document.status == DocumentStatus.QA_SPLITTING
    assert document.chunk_count == 2
    assert job.stage == "QA_SPLITTING"
    assert job.progress == 40
    assert len(chunks) == 2
    assert [chunk.chunk_index for chunk in chunks] == [0, 1]
    assert len(artifacts) == 1
    assert artifacts[0].artifact_type == "PARSED_MARKDOWN"


def test_parse_document_service_fails_when_no_content_blocks_extracted(tmp_path):
    session, identity, storage = build_parse_session(tmp_path)
    # A heading-only markdown extracts to zero content blocks: headings shape
    # the title_path breadcrumb but are never emitted as blocks.
    job_id, document_id = create_uploaded_job(
        session,
        identity,
        storage,
        b"# Title Only\n\n## Another Heading\n",
    )

    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob
    from server.app.models.logs import TaskRun
    from server.app.models.qa_pair import DocumentChunk
    from server.app.services.document_parse_service import DocumentParseService

    result = DocumentParseService(session, storage=storage).parse_import_job(job_id)

    document = session.get(Document, document_id)
    job = session.get(ImportJob, job_id)
    task_run = session.scalar(select(TaskRun).where(TaskRun.resource_id == job_id))
    chunks = session.scalars(
        select(DocumentChunk).where(DocumentChunk.document_id == document_id)
    ).all()

    # Fails at the parse stage (not deferred to QA split) with an actionable code.
    assert result.status == "FAILED"
    assert result.stage == "PARSING"
    assert document.status == DocumentStatus.FAILED
    assert document.last_error_code == "PARSER_NO_CONTENT"
    assert job.error_code == "PARSER_NO_CONTENT"
    assert task_run.error["code"] == "PARSER_NO_CONTENT"
    assert task_run.error["retryable"] is False
    assert len(chunks) == 0


def test_parse_document_service_records_retryable_failure_when_mineru_unreachable(
    monkeypatch, tmp_path
):
    import httpx

    from server.app.integrations.parsers.mineru import MinerUClient, MinerUParser
    from server.tests.test_mineru_parser import _patch_transport

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _patch_transport(monkeypatch, handler)

    session, identity, storage = build_parse_session(tmp_path)
    job_id, document_id = create_uploaded_job(
        session,
        identity,
        storage,
        b"%PDF-1.7",
        object_key="uploads/doc.pdf",
    )

    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob
    from server.app.models.logs import TaskRun
    from server.app.services.document_parse_service import DocumentParseService

    parser = MinerUParser(MinerUClient("http://mineru.test", max_retries=0))
    service = DocumentParseService(session, storage=storage, parsers=[parser])
    result = service.parse_import_job(job_id)

    document = session.get(Document, document_id)
    job = session.get(ImportJob, job_id)
    task_run = session.scalar(select(TaskRun).where(TaskRun.resource_id == job_id))

    assert result.status == "FAILED"
    assert document.status == DocumentStatus.FAILED
    assert document.last_error_code == "PARSER_UNAVAILABLE"
    assert job.error_code == "PARSER_UNAVAILABLE"
    assert task_run.status == "FAILED"
    assert task_run.error["code"] == "PARSER_UNAVAILABLE"
    assert task_run.error["retryable"] is True


def test_parse_document_service_rejects_unsupported_type_when_mineru_unconfigured(
    tmp_path,
):
    session, identity, storage = build_parse_session(tmp_path)
    job_id, document_id = create_uploaded_job(
        session,
        identity,
        storage,
        b"%PDF-1.7",
        object_key="uploads/doc.pdf",
    )

    from server.app.integrations.parsers.csv_parser import CsvParser
    from server.app.integrations.parsers.lightweight import LightweightParser
    from server.app.integrations.parsers.mineru import MinerUClient, MinerUParser
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.logs import TaskRun
    from server.app.services.document_parse_service import DocumentParseService

    parsers = [LightweightParser(), CsvParser(), MinerUParser(MinerUClient(None))]
    result = DocumentParseService(
        session, storage=storage, parsers=parsers
    ).parse_import_job(job_id)

    document = session.get(Document, document_id)
    task_run = session.scalar(select(TaskRun).where(TaskRun.resource_id == job_id))

    assert result.status == "FAILED"
    assert document.status == DocumentStatus.FAILED
    assert document.last_error_code == "UNSUPPORTED_FILE_TYPE"
    assert task_run.error["retryable"] is False


def test_parse_document_service_ingests_csv_via_registry_chain(tmp_path):
    session, identity, storage = build_parse_session(tmp_path)
    job_id, document_id = create_uploaded_job(
        session,
        identity,
        storage,
        "姓名,部门\n张三,售后\n李四,财务\n".encode(),
        object_key="uploads/staff.csv",
    )

    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ParseArtifact
    from server.app.models.qa_pair import DocumentChunk
    from server.app.services.document_parse_service import DocumentParseService

    DocumentParseService(session, storage=storage).parse_import_job(job_id)

    document = session.get(Document, document_id)
    chunks = session.scalars(
        select(DocumentChunk).where(DocumentChunk.document_id == document_id)
    ).all()
    artifacts = session.scalars(
        select(ParseArtifact).where(ParseArtifact.document_id == document_id)
    ).all()

    assert document.status == DocumentStatus.QA_SPLITTING
    assert document.parser_name == "CSV"
    assert len(chunks) == 1
    assert chunks[0].content.splitlines()[0] == "| 姓名 | 部门 |"
    assert chunks[0].token_count > 0
    assert chunks[0].source_locator == {"rowStart": 2, "rowEnd": 3}
    assert len(artifacts) == 1



def _parse_chunker():
    from dataclasses import dataclass
    from server.app.services.chunking import ChunkingService

    @dataclass(frozen=True)
    class Counter:
        name: str = "parse-test-counter"
        version: str = "1.0"
        def count(self, text): return len(text.split())
        def split_by_token_limit(self, text, limit):
            words = text.split()
            return [" ".join(words[i:i + limit]) for i in range(0, len(words), limit)]
    return ChunkingService(Counter())


def _parse_policy():
    from server.app.services.chunking import ChunkPolicy
    counter = _parse_chunker()._token_counter
    return ChunkPolicy(tokenizer_name=counter.name, tokenizer_version=counter.version,
                       min_tokens=2, target_tokens=3, max_tokens=4, overlap_tokens=0,
                       parent_max_tokens=8, embedding_provider_input_limit=16)

def test_parse_document_service_persists_adaptive_parent_before_children_and_config(tmp_path):
    """Adaptive ingestion writes parents first, then linked active children."""
    from dataclasses import dataclass

    from server.app.models.qa_pair import DocumentChunk
    from server.app.services.chunking import ChunkPolicy, ChunkingService
    from server.app.services.document_parse_service import DocumentParseService

    @dataclass(frozen=True)
    class Counter:
        name: str = "parse-test-counter"
        version: str = "1.0"
        def count(self, text): return len(text.split())
        def split_by_token_limit(self, text, limit):
            words = text.split()
            return [" ".join(words[i:i + limit]) for i in range(0, len(words), limit)]

    session, identity, storage = build_parse_session(tmp_path)
    job_id, document_id = create_uploaded_job(
        session, identity, storage,
        b"# Guide\n\nalpha beta gamma delta.\n\n## Next\n\nepsilon zeta eta theta.",
    )
    counter = Counter()
    policy = ChunkPolicy(
        tokenizer_name=counter.name, tokenizer_version=counter.version,
        min_tokens=2, target_tokens=3, max_tokens=4, overlap_tokens=0,
        parent_max_tokens=8, embedding_provider_input_limit=16,
    )
    service = DocumentParseService(
        session, storage=storage, adaptive_chunking=True,
        chunking_service=ChunkingService(counter), chunking_policy=policy,
    )
    service.parse_import_job(job_id)
    chunks = session.scalars(
        select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_level, DocumentChunk.chunk_index)
    ).all()
    parents = [chunk for chunk in chunks if chunk.chunk_level == "PARENT"]
    children = [chunk for chunk in chunks if chunk.chunk_level == "CHILD"]

    assert parents and children
    assert all(child.parent_chunk_id in {parent.id for parent in parents} for child in children)
    assert all(chunk.status == "ACTIVE" for chunk in chunks)
    assert all(chunk.chunker_name == policy.name for chunk in chunks)
    assert all(chunk.chunker_version == policy.version for chunk in chunks)
    assert all(chunk.chunker_config_hash == policy.config_hash for chunk in chunks)
    assert all(chunk.chunk_metadata["chunker"]["configHash"] == policy.config_hash for chunk in chunks)


def test_adaptive_parse_failure_rolls_back_staged_collection_and_keeps_old_active(tmp_path, monkeypatch):
    from server.app.models.import_job import ImportJob
    from server.app.models.logs import TaskRun
    from server.app.models.qa_pair import DocumentChunk
    from server.app.services.document_parse_service import DocumentParseService

    session, identity, storage = build_parse_session(tmp_path)
    job_id, document_id = create_uploaded_job(
        session, identity, storage, b"# Guide\n\nnew alpha beta gamma delta.",
    )
    old = DocumentChunk(
        tenant_id=identity["tenant"].id, document_id=document_id, chunk_index=0,
        content="old active", token_count=2, source_locator={"legacy": 0},
        status="ACTIVE",
    )
    session.add(old)
    session.commit()
    service = DocumentParseService(session, storage=storage, adaptive_chunking=True,
                                   chunking_service=_parse_chunker(), chunking_policy=_parse_policy())
    original = service._chunk_row
    calls = 0
    def fail_on_child(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("child insert failed")
        return original(*args, **kwargs)
    monkeypatch.setattr(service, "_chunk_row", fail_on_child)

    service.parse_import_job(job_id)
    rows = session.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id)).all()
    assert [(row.content, row.status) for row in rows] == [("old active", "ACTIVE")]
    assert session.get(DocumentChunk, old.id).status == "ACTIVE"
    failed_job = session.get(ImportJob, job_id)
    failed_run = session.scalar(select(TaskRun).where(TaskRun.resource_id == job_id))
    assert failed_job.stage == "CHUNKING"
    assert failed_run.stage == "CHUNKING"


def test_legacy_parse_mode_keeps_one_active_row_per_parser_block(tmp_path):
    session, identity, storage = build_parse_session(tmp_path)
    job_id, document_id = create_uploaded_job(
        session, identity, storage, b"# Guide\n\none.\n\n## Next\n\ntwo.",
    )
    from server.app.models.qa_pair import DocumentChunk
    from server.app.services.document_parse_service import DocumentParseService

    DocumentParseService(session, storage=storage).parse_import_job(job_id)
    chunks = session.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id)).all()
    assert len(chunks) == 2
    assert all(chunk.chunk_level == "CHILD" and chunk.parent_chunk_id is None for chunk in chunks)
    assert all(chunk.chunker_name == "legacy_parser" and chunk.status == "ACTIVE" for chunk in chunks)


def test_adaptive_parse_retry_with_same_config_is_a_noop_before_taskrun_and_artifact(tmp_path):
    from sqlalchemy import func

    from server.app.models.import_job import ParseArtifact
    from server.app.models.logs import TaskRun
    from server.app.models.qa_pair import DocumentChunk, QaPair
    from server.app.services.document_parse_service import DocumentParseService

    session, identity, storage = build_parse_session(tmp_path)
    job_id, document_id = create_uploaded_job(
        session, identity, storage, b"# Guide\n\nalpha beta gamma delta.",
    )
    service = DocumentParseService(
        session, storage=storage, adaptive_chunking=True,
        chunking_service=_parse_chunker(), chunking_policy=_parse_policy(),
    )
    service.parse_import_job(job_id)
    active_children = session.scalars(
        select(DocumentChunk).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.status == "ACTIVE",
            DocumentChunk.chunk_level == "CHILD",
        )
    ).all()
    session.add(QaPair(
        tenant_id=identity["tenant"].id, document_id=document_id,
        chunk_id=active_children[0].id, job_id=job_id, pair_index=0,
        question="q", answer="a", quote="alpha", page_no=1,
    ))
    session.commit()
    active_ids = {chunk.id for chunk in active_children}
    chunk_total = session.scalar(select(func.count()).select_from(DocumentChunk))
    artifact_total = session.scalar(select(func.count()).select_from(ParseArtifact))
    run_total = session.scalar(select(func.count()).select_from(TaskRun))

    service.parse_import_job(job_id)

    assert {chunk.id for chunk in session.scalars(select(DocumentChunk).where(DocumentChunk.status == "ACTIVE")).all()} == active_ids | {
        chunk.id for chunk in session.scalars(select(DocumentChunk).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.status == "ACTIVE", DocumentChunk.chunk_level == "PARENT",
        )).all()
    }
    assert session.scalar(select(func.count()).select_from(DocumentChunk)) == chunk_total
    assert session.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.status == "SUPERSEDED")) == 0
    assert session.scalar(select(func.count()).select_from(ParseArtifact)) == artifact_total
    assert session.scalar(select(func.count()).select_from(TaskRun)) == run_total
    assert session.scalar(select(QaPair.chunk_id)) == active_children[0].id


def test_adaptive_failed_rebuild_never_overwrites_referenced_artifact_bytes(tmp_path, monkeypatch):
    from server.app.models.import_job import ParseArtifact
    from server.app.services.chunking import ChunkPolicy
    from server.app.services.document_parse_service import DocumentParseService

    session, identity, storage = build_parse_session(tmp_path)
    job_id, document_id = create_uploaded_job(
        session, identity, storage, b"# Guide\n\nold alpha beta gamma delta.",
    )
    stable = DocumentParseService(
        session, storage=storage, adaptive_chunking=True,
        chunking_service=_parse_chunker(), chunking_policy=_parse_policy(),
    )
    stable.parse_import_job(job_id)
    artifact = session.scalar(select(ParseArtifact).where(ParseArtifact.document_id == document_id))
    old_key, old_bytes, old_hash = artifact.object_key, storage.get_object(artifact.object_key), artifact.content_hash
    changed_policy = ChunkPolicy(
        tokenizer_name="parse-test-counter", tokenizer_version="1.0",
        min_tokens=2, target_tokens=4, max_tokens=5, overlap_tokens=0,
        parent_max_tokens=10, embedding_provider_input_limit=16,
    )
    rebuilding = DocumentParseService(
        session, storage=storage, adaptive_chunking=True,
        chunking_service=_parse_chunker(), chunking_policy=changed_policy,
    )
    monkeypatch.setattr(rebuilding, "_write_adaptive_chunks", lambda *_args: (_ for _ in ()).throw(RuntimeError("db fail")))
    job = session.get(__import__("server.app.models.import_job", fromlist=["ImportJob"]).ImportJob, job_id)
    document = session.get(__import__("server.app.models.document", fromlist=["Document"]).Document, document_id)
    with pytest.raises(RuntimeError, match="db fail"):
        rebuilding._replace_parse_outputs(job, document, "new markdown", [])
    session.rollback()
    artifact = session.scalar(select(ParseArtifact).where(ParseArtifact.document_id == document_id))
    assert (artifact.object_key, artifact.content_hash) == (old_key, old_hash)
    assert storage.get_object(old_key) == old_bytes
    assert [path for path in (storage.root / "artifacts" / document_id / "parsed").glob("*.md")] == [
        storage.root / old_key
    ]


def test_qa_lists_only_active_children_from_one_adaptive_config(tmp_path):
    from server.app.models.qa_pair import DocumentChunk
    from server.app.services.document_parse_service import DocumentParseService
    from server.app.services.qa_split_service import QaSplitService

    session, identity, storage = build_parse_session(tmp_path)
    job_id, document_id = create_uploaded_job(
        session, identity, storage, b"# Guide\n\nalpha beta gamma delta.\n\n## B\n\nepsilon zeta eta theta.",
    )
    DocumentParseService(
        session, storage=storage, adaptive_chunking=True,
        chunking_service=_parse_chunker(), chunking_policy=_parse_policy(),
    ).parse_import_job(job_id)
    chunks = QaSplitService(session)._list_chunks(document_id)
    assert chunks
    assert all(chunk.status == "ACTIVE" and chunk.chunk_level == "CHILD" for chunk in chunks)
    assert len({chunk.chunk_index for chunk in chunks}) == len(chunks)
    assert len({chunk.chunker_config_hash for chunk in chunks}) == 1
    assert not any(chunk.chunk_level == "PARENT" for chunk in chunks)


def test_adaptive_parse_locks_document_before_checking_current_collection(tmp_path, monkeypatch):
    """PostgreSQL workers must serialize the collection check behind FOR UPDATE."""
    from server.app.services.document_parse_service import DocumentParseService

    session, identity, storage = build_parse_session(tmp_path)
    job_id, _ = create_uploaded_job(session, identity, storage, b"# Guide\n\nalpha beta gamma delta.")
    seen_lock = False
    original_scalar = session.scalar
    def inspect_lock(statement, *args, **kwargs):
        nonlocal seen_lock
        if getattr(statement, "_for_update_arg", None) is not None:
            seen_lock = True
        return original_scalar(statement, *args, **kwargs)
    monkeypatch.setattr(session, "scalar", inspect_lock)
    DocumentParseService(session, storage=storage, adaptive_chunking=True,
                         chunking_service=_parse_chunker(), chunking_policy=_parse_policy()).parse_import_job(job_id)
    assert seen_lock


def test_successful_adaptive_rebuild_reclaims_unreferenced_old_artifact(tmp_path):
    from server.app.integrations.storage.base import ObjectStorageAdapter
    from server.app.models.import_job import ParseArtifact
    from server.app.services.chunking import ChunkPolicy
    from server.app.services.document_parse_service import DocumentParseService

    session, identity, storage = build_parse_session(tmp_path)
    job_id, document_id = create_uploaded_job(session, identity, storage, b"# Guide\n\nalpha beta gamma delta.")
    DocumentParseService(session, storage=storage, adaptive_chunking=True,
                         chunking_service=_parse_chunker(), chunking_policy=_parse_policy()).parse_import_job(job_id)
    old_key = session.scalar(select(ParseArtifact.object_key).where(ParseArtifact.document_id == document_id))
    changed = ChunkPolicy(tokenizer_name="parse-test-counter", tokenizer_version="1.0",
                          min_tokens=2, target_tokens=4, max_tokens=5, overlap_tokens=0,
                          parent_max_tokens=10, embedding_provider_input_limit=16)
    DocumentParseService(session, storage=storage, adaptive_chunking=True,
                         chunking_service=_parse_chunker(), chunking_policy=changed).parse_import_job(job_id)
    artifact = session.scalar(select(ParseArtifact).where(ParseArtifact.document_id == document_id))
    assert artifact.object_key != old_key
    with pytest.raises(FileNotFoundError):
        storage.get_object(old_key)


def test_failed_attempt_records_gc_marker_without_harming_old_active_artifact(tmp_path, monkeypatch):
    from server.app.models.import_job import ParseArtifact
    from server.app.services.chunking import ChunkPolicy
    from server.app.services.document_parse_service import DocumentParseService

    session, identity, local_storage = build_parse_session(tmp_path)
    job_id, document_id = create_uploaded_job(
        session, identity, local_storage, b"# Guide\n\nalpha beta gamma delta."
    )
    DocumentParseService(
        session, storage=local_storage, adaptive_chunking=True,
        chunking_service=_parse_chunker(), chunking_policy=_parse_policy(),
    ).parse_import_job(job_id)
    old_artifact = session.scalar(
        select(ParseArtifact).where(ParseArtifact.document_id == document_id,
                                    ParseArtifact.artifact_type == "PARSED_MARKDOWN")
    )
    old_key, old_bytes = old_artifact.object_key, local_storage.get_object(old_artifact.object_key)

    class DeleteFailsStorage(type(local_storage)):
        def delete_object(self, object_key):
            raise OSError("storage delete unavailable")

    changed = ChunkPolicy(
        tokenizer_name="parse-test-counter", tokenizer_version="1.0",
        min_tokens=2, target_tokens=4, max_tokens=5, overlap_tokens=0,
        parent_max_tokens=10, embedding_provider_input_limit=16,
    )
    storage = DeleteFailsStorage(local_storage.root)
    service = DocumentParseService(session, storage=storage, adaptive_chunking=True,
                                   chunking_service=_parse_chunker(), chunking_policy=changed)
    monkeypatch.setattr(service, "_write_adaptive_chunks", lambda *_args: (_ for _ in ()).throw(RuntimeError("db fail")))
    service.parse_import_job(job_id)

    parsed = session.scalar(
        select(ParseArtifact).where(ParseArtifact.document_id == document_id,
                                    ParseArtifact.artifact_type == "PARSED_MARKDOWN")
    )
    markers = session.scalars(
        select(ParseArtifact).where(ParseArtifact.document_id == document_id,
                                    ParseArtifact.artifact_type == "ORPHANED_OBJECT_GC_PENDING")
    ).all()
    assert (parsed.object_key, storage.get_object(old_key)) == (old_key, old_bytes)
    assert len(markers) == 1
    assert markers[0].artifact_metadata["gcReason"] == "PARSE_ATTEMPT_ROLLBACK"


def test_two_worker_sessions_leave_one_active_adaptive_collection(tmp_path):
    from sqlalchemy import func
    from sqlalchemy.orm import sessionmaker

    from server.app.models.import_job import ParseArtifact
    from server.app.models.logs import TaskRun
    from server.app.models.qa_pair import DocumentChunk
    from server.app.services.document_parse_service import DocumentParseService

    session, identity, storage = build_parse_session(tmp_path)
    job_id, document_id = create_uploaded_job(
        session, identity, storage, b"# Guide\n\nalpha beta gamma delta."
    )
    worker_two_session = sessionmaker(bind=session.bind, autoflush=False)()
    one = DocumentParseService(session, storage=storage, adaptive_chunking=True,
                               chunking_service=_parse_chunker(), chunking_policy=_parse_policy())
    two = DocumentParseService(worker_two_session, storage=storage, adaptive_chunking=True,
                               chunking_service=_parse_chunker(), chunking_policy=_parse_policy())
    one.parse_import_job(job_id)
    two.parse_import_job(job_id)

    active = session.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id,
                                                         DocumentChunk.status == "ACTIVE")).all()
    children = [chunk for chunk in active if chunk.chunk_level == "CHILD"]
    assert len({chunk.chunk_index for chunk in children}) == len(children)
    assert len({chunk.chunker_config_hash for chunk in active}) == 1
    assert session.scalar(select(func.count()).select_from(TaskRun).where(TaskRun.resource_id == job_id,
                                                                          TaskRun.status == "SUCCESS")) == 1
    assert session.scalar(select(func.count()).select_from(ParseArtifact).where(ParseArtifact.document_id == document_id,
                                                                                 ParseArtifact.artifact_type == "PARSED_MARKDOWN")) == 1
    assert session.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == document_id,
                                                                                 DocumentChunk.status == "SUPERSEDED")) == 0


def test_post_commit_gc_marker_failure_cannot_fail_committed_adaptive_parse(tmp_path, monkeypatch):
    """GC failures after the primary commit must never rewrite parse success."""
    from sqlalchemy.exc import SQLAlchemyError

    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob, ParseArtifact
    from server.app.models.logs import TaskRun
    from server.app.models.qa_pair import DocumentChunk
    from server.app.services.chunking import ChunkPolicy
    from server.app.services.document_parse_service import DocumentParseService

    session, identity, local_storage = build_parse_session(tmp_path)
    job_id, document_id = create_uploaded_job(
        session, identity, local_storage, b"# Guide\n\nalpha beta gamma delta."
    )
    DocumentParseService(
        session, storage=local_storage, adaptive_chunking=True,
        chunking_service=_parse_chunker(), chunking_policy=_parse_policy(),
    ).parse_import_job(job_id)
    old_key = session.scalar(
        select(ParseArtifact.object_key).where(
            ParseArtifact.document_id == document_id,
            ParseArtifact.artifact_type == "PARSED_MARKDOWN",
        )
    )

    class DeleteFailsStorage(type(local_storage)):
        def delete_object(self, object_key):
            raise OSError("storage delete unavailable")

    changed = ChunkPolicy(
        tokenizer_name="parse-test-counter", tokenizer_version="1.0",
        min_tokens=2, target_tokens=4, max_tokens=5, overlap_tokens=0,
        parent_max_tokens=10, embedding_provider_input_limit=16,
    )
    service = DocumentParseService(
        session, storage=DeleteFailsStorage(local_storage.root), adaptive_chunking=True,
        chunking_service=_parse_chunker(), chunking_policy=changed,
    )
    # This simulates the durable GC marker write/commit path being unavailable
    # after a storage deletion failure.  The parse transaction is already
    # committed at this point and must remain successful.
    monkeypatch.setattr(
        service,
        "_queue_artifact_gc_marker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SQLAlchemyError("marker DB unavailable")),
    )

    service.parse_import_job(job_id)
    session.expire_all()

    document = session.get(Document, document_id)
    job = session.get(ImportJob, job_id)
    task_run = session.scalar(
        select(TaskRun).where(TaskRun.resource_id == job_id).order_by(TaskRun.created_at.desc())
    )
    active_chunks = session.scalars(
        select(DocumentChunk).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.status == "ACTIVE",
        )
    ).all()
    new_artifact = session.scalar(
        select(ParseArtifact).where(
            ParseArtifact.document_id == document_id,
            ParseArtifact.artifact_type == "PARSED_MARKDOWN",
        )
    )

    assert document.status == DocumentStatus.QA_SPLITTING
    assert job.stage == "QA_SPLITTING"
    assert task_run.status == "SUCCESS"
    assert {chunk.chunk_level for chunk in active_chunks} == {"PARENT", "CHILD"}
    assert new_artifact.object_key != old_key
