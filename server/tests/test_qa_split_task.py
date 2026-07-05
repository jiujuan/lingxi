from sqlalchemy import select


def build_qa_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from server.app.db.base import Base
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
    return session, identity


def add_default_qa_model(session, tenant_id: str, response):
    from server.app.core.secrets import encrypt_secret
    from server.app.models.model_config import ModelConfig, ModelProvider

    provider = ModelProvider(
        tenant_id=tenant_id,
        provider_type="OPENAI_COMPATIBLE",
        name="Fake QA Provider",
        base_url="mock://success",
        encrypted_api_key=encrypt_secret("sk-qa"),
        status="ACTIVE",
        config={},
    )
    session.add(provider)
    session.flush()
    model = ModelConfig(
        tenant_id=tenant_id,
        provider_id=provider.id,
        capability="QA_SPLIT",
        model_name="fake-qa",
        is_default=True,
        status="ACTIVE",
        config={"qaSplitResponse": response},
    )
    session.add(model)
    session.flush()
    return model


def create_qa_ready_job(session, identity):
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob, ImportJobStatus
    from server.app.models.qa_pair import DocumentChunk

    tenant_id = identity["tenant"].id
    document = Document(
        tenant_id=tenant_id,
        title="Refund SOP",
        file_name="refund.md",
        file_type="MARKDOWN",
        mime_type="text/markdown",
        file_size=100,
        object_key="uploads/refund.md",
        checksum="refund",
        status=DocumentStatus.QA_SPLITTING,
        chunk_count=2,
    )
    session.add(document)
    session.flush()
    job = ImportJob(
        tenant_id=tenant_id,
        document_id=document.id,
        status=ImportJobStatus.RUNNING.value,
        stage="QA_SPLITTING",
        progress=40,
    )
    session.add(job)
    session.flush()
    chunks = [
        DocumentChunk(
            tenant_id=tenant_id,
            document_id=document.id,
            job_id=job.id,
            chunk_index=0,
            content="退款需要主管审批。",
            page_no=1,
            title_path=["退款流程"],
            source_locator={"lineStart": 1},
        ),
        DocumentChunk(
            tenant_id=tenant_id,
            document_id=document.id,
            job_id=job.id,
            chunk_index=1,
            content="已开票订单需先红冲发票。",
            page_no=2,
            title_path=["发票处理"],
            source_locator={"lineStart": 4},
        ),
    ]
    session.add_all(chunks)
    session.commit()
    return job.id, document.id, chunks


def test_qa_split_validator_rejects_invalid_json_and_missing_fields():
    from server.app.services.qa_split_service import (
        QaSplitValidationError,
        validate_qa_split_output,
    )

    valid = validate_qa_split_output(
        '{"items":[{"question":"怎么退款？","answer":"需要审批。","quote":"退款需要主管审批。","pageNo":1}]}'
    )
    assert valid[0].question == "怎么退款？"

    for payload in ["not-json", '{"items":[{"question":"缺少答案"}]}']:
        try:
            validate_qa_split_output(payload)
        except QaSplitValidationError as exc:
            assert exc.code == "QA_SPLIT_INVALID_OUTPUT"
        else:
            raise AssertionError("invalid QA output should fail validation")


def test_qa_split_service_writes_pairs_and_is_idempotent():
    session, identity = build_qa_session()
    tenant_id = identity["tenant"].id
    job_id, document_id, chunks = create_qa_ready_job(session, identity)
    add_default_qa_model(
        session,
        tenant_id,
        {
            "items": [
                {
                    "question": "退款需要谁审批？",
                    "answer": "退款需要主管审批。",
                    "quote": "退款需要主管审批。",
                    "pageNo": 1,
                    "chunkIndex": 0,
                },
                {
                    "question": "已开票订单退款前要做什么？",
                    "answer": "需要先红冲发票。",
                    "quote": "已开票订单需先红冲发票。",
                    "pageNo": 2,
                    "chunkIndex": 1,
                },
            ]
        },
    )

    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob
    from server.app.models.qa_pair import QaPair
    from server.app.services.qa_split_service import QaSplitService

    service = QaSplitService(session)
    first = service.split_import_job(job_id)
    second = service.split_import_job(job_id)

    document = session.get(Document, document_id)
    job = session.get(ImportJob, job_id)
    qa_pairs = session.scalars(
        select(QaPair).where(QaPair.document_id == document_id).order_by(QaPair.pair_index)
    ).all()

    assert first.stage == "EMBEDDING"
    assert second.stage == "EMBEDDING"
    assert document.status == DocumentStatus.EMBEDDING
    assert document.qa_pair_count == 2
    assert job.progress == 65
    assert len(qa_pairs) == 2
    assert qa_pairs[0].chunk_id == chunks[0].id
    assert qa_pairs[1].page_no == 2
    assert qa_pairs[1].quote == "已开票订单需先红冲发票。"


def test_qa_split_failure_records_error_and_keeps_chunks():
    session, identity = build_qa_session()
    tenant_id = identity["tenant"].id
    job_id, document_id, _chunks = create_qa_ready_job(session, identity)
    add_default_qa_model(session, tenant_id, "not-json")

    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob
    from server.app.models.logs import TaskRun
    from server.app.models.qa_pair import DocumentChunk, QaPair
    from server.app.services.qa_split_service import QaSplitService

    result = QaSplitService(session).split_import_job(job_id)

    document = session.get(Document, document_id)
    job = session.get(ImportJob, job_id)
    chunks = session.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id)).all()
    qa_pairs = session.scalars(select(QaPair).where(QaPair.document_id == document_id)).all()
    task_run = session.scalar(select(TaskRun).where(TaskRun.resource_id == job_id))

    assert result.status == "FAILED"
    assert document.status == DocumentStatus.FAILED
    assert document.last_error_code == "QA_SPLIT_INVALID_OUTPUT"
    assert job.error_code == "QA_SPLIT_INVALID_OUTPUT"
    assert len(chunks) == 2
    assert qa_pairs == []
    assert task_run.status == "FAILED"


def test_qa_regeneration_api_and_qa_pair_list():
    from server.tests.test_auth_rbac import build_test_client
    from server.tests.test_model_config import login_admin

    client, SessionLocal = build_test_client()
    headers = login_admin(client)

    with SessionLocal() as session:
        from server.app.models.user import Tenant

        tenant = session.scalar(select(Tenant))
        job_id, document_id, _chunks = create_qa_ready_job(
            session,
            {"tenant": tenant},
        )
        add_default_qa_model(
            session,
            tenant.id,
            {
                "items": [
                    {
                        "question": "退款怎么审批？",
                        "answer": "由主管审批。",
                        "quote": "退款需要主管审批。",
                        "pageNo": 1,
                        "chunkIndex": 0,
                    }
                ]
            },
        )
        session.commit()

    regenerated = client.post(
        f"/api/v1/documents/{document_id}/qa-regenerations",
        headers=headers,
    )
    assert regenerated.status_code == 200
    assert regenerated.json()["stage"] == "EMBEDDING"

    listed = client.get(
        f"/api/v1/documents/{document_id}/qa-pairs?page=1&pageSize=10",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()["pagination"]["totalItems"] == 1
    assert listed.json()["data"][0]["question"] == "退款怎么审批？"
