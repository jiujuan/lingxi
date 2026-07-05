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
    mime_type = "application/pdf" if file_name.endswith(".pdf") else "text/markdown"

    document = Document(
        tenant_id=tenant_id,
        title="Parser Guide",
        file_name=file_name,
        file_type="PDF" if file_name.endswith(".pdf") else "MARKDOWN",
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


def test_parse_document_service_records_failure(tmp_path):
    session, identity, storage = build_parse_session(tmp_path)
    job_id, document_id = create_uploaded_job(
        session,
        identity,
        storage,
        b"%PDF-not-supported",
        object_key="uploads/doc.pdf",
    )

    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob
    from server.app.models.logs import TaskRun
    from server.app.services.document_parse_service import DocumentParseService

    result = DocumentParseService(session, storage=storage).parse_import_job(job_id)

    document = session.get(Document, document_id)
    job = session.get(ImportJob, job_id)
    task_run = session.scalar(select(TaskRun).where(TaskRun.resource_id == job_id))

    assert result.status == "FAILED"
    assert document.status == DocumentStatus.FAILED
    assert document.last_error_code == "PARSER_UNAVAILABLE"
    assert job.status == "FAILED"
    assert job.error_code == "PARSER_UNAVAILABLE"
    assert task_run.status == "FAILED"
    assert task_run.error["code"] == "PARSER_UNAVAILABLE"
