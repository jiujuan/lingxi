from sqlalchemy import select


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
