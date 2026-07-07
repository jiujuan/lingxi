from sqlalchemy import select

from server.tests.test_qa_split_task import build_qa_session, create_qa_ready_job


def add_default_embedding_model(
    session,
    tenant_id: str,
    expected_dimension: int = 4,
    provider_dimension: int | None = None,
):
    from server.app.core.secrets import encrypt_secret
    from server.app.models.model_config import ModelConfig, ModelProvider

    provider = ModelProvider(
        tenant_id=tenant_id,
        provider_type="OPENAI_COMPATIBLE",
        name=f"Fake Embedding Provider {expected_dimension}-{provider_dimension}",
        base_url="mock://success",
        encrypted_api_key=encrypt_secret("sk-embedding"),
        status="ACTIVE",
        config={},
    )
    session.add(provider)
    session.flush()
    model = ModelConfig(
        tenant_id=tenant_id,
        provider_id=provider.id,
        capability="EMBEDDING",
        model_name="fake-embedding",
        embedding_dimension=expected_dimension,
        is_default=True,
        status="ACTIVE",
        config={"embeddingDimension": provider_dimension or expected_dimension},
    )
    session.add(model)
    session.flush()
    return model


def add_qa_pairs(session, tenant_id: str, document_id: str, job_id: str, chunk_ids: list[str]):
    from server.app.models.qa_pair import QaPair

    pairs = [
        QaPair(
            tenant_id=tenant_id,
            document_id=document_id,
            chunk_id=chunk_ids[0],
            job_id=job_id,
            pair_index=0,
            question="退款需要谁审批？",
            answer="退款需要主管审批。",
            quote="退款需要主管审批。",
            page_no=1,
            search_text="",
            status="ACTIVE",
        ),
        QaPair(
            tenant_id=tenant_id,
            document_id=document_id,
            chunk_id=chunk_ids[1],
            job_id=job_id,
            pair_index=1,
            question="已开票订单退款前要做什么？",
            answer="需要先红冲发票。",
            quote="已开票订单需先红冲发票。",
            page_no=2,
            search_text="",
            status="ACTIVE",
        ),
    ]
    session.add_all(pairs)
    session.commit()
    return pairs


def prepare_embedding_job(session, identity):
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob, ImportJobStatus

    job_id, document_id, chunks = create_qa_ready_job(session, identity)
    document = session.get(Document, document_id)
    job = session.get(ImportJob, job_id)
    document.status = DocumentStatus.EMBEDDING
    job.stage = "EMBEDDING"
    job.status = ImportJobStatus.RUNNING.value
    job.progress = 65
    session.commit()
    return job_id, document_id, chunks


def test_jieba_tokenizer_generates_search_text():
    from server.app.integrations.tokenizers.jieba_tokenizer import JiebaTokenizer

    search_text = JiebaTokenizer().to_search_text("退款 SOP 2026")

    assert search_text == "退款 sop 2026"


def test_embedding_service_writes_vectors_search_text_and_ready_idempotently():
    session, identity = build_qa_session()
    tenant_id = identity["tenant"].id
    job_id, document_id, chunks = prepare_embedding_job(session, identity)
    add_default_embedding_model(session, tenant_id, expected_dimension=4)
    add_qa_pairs(session, tenant_id, document_id, job_id, [chunk.id for chunk in chunks])

    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob
    from server.app.models.logs import TaskRun
    from server.app.models.qa_pair import QaPair
    from server.app.services.embedding_service import EmbeddingService

    service = EmbeddingService(session)
    first = service.embed_import_job(job_id)
    second = service.embed_import_job(job_id)

    document = session.get(Document, document_id)
    job = session.get(ImportJob, job_id)
    qa_pairs = session.scalars(
        select(QaPair).where(QaPair.document_id == document_id).order_by(QaPair.pair_index)
    ).all()
    task_runs = session.scalars(select(TaskRun).where(TaskRun.resource_id == job_id)).all()

    assert first.status == "COMPLETED"
    assert second.status == "COMPLETED"
    assert document.status == DocumentStatus.READY
    assert document.qa_pair_count == 2
    assert document.chunk_count == 2
    assert job.stage == "COMPLETED"
    assert job.progress == 100
    assert len(qa_pairs) == 2
    assert len(qa_pairs[0].question_embedding) == 4
    assert "退款" in qa_pairs[0].search_text
    assert all(item.status == "ACTIVE" for item in qa_pairs)
    assert all(task.status == "SUCCESS" for task in task_runs)


def test_embedding_dimension_mismatch_records_failure_without_deleting_qa_pairs():
    session, identity = build_qa_session()
    tenant_id = identity["tenant"].id
    job_id, document_id, chunks = prepare_embedding_job(session, identity)
    add_default_embedding_model(
        session,
        tenant_id,
        expected_dimension=4,
        provider_dimension=3,
    )
    add_qa_pairs(session, tenant_id, document_id, job_id, [chunk.id for chunk in chunks])

    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob
    from server.app.models.logs import TaskRun
    from server.app.models.qa_pair import QaPair
    from server.app.services.embedding_service import EmbeddingService

    result = EmbeddingService(session).embed_import_job(job_id)

    document = session.get(Document, document_id)
    job = session.get(ImportJob, job_id)
    qa_pairs = session.scalars(
        select(QaPair).where(QaPair.document_id == document_id).order_by(QaPair.pair_index)
    ).all()
    task_run = session.scalar(select(TaskRun).where(TaskRun.resource_id == job_id))

    assert result.status == "FAILED"
    assert document.status == DocumentStatus.FAILED
    assert document.last_error_code == "EMBEDDING_DIMENSION_MISMATCH"
    assert job.error_code == "EMBEDDING_DIMENSION_MISMATCH"
    assert len(qa_pairs) == 2
    assert all(item.status == "EMBEDDING_FAILED" for item in qa_pairs)
    assert task_run.status == "FAILED"
    assert task_run.error["code"] == "EMBEDDING_DIMENSION_MISMATCH"
