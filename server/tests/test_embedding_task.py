from hashlib import sha256

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


class _RecordingEmbeddingAdapter:
    def __init__(
        self,
        dimension: int = 4,
        bad_call_index: int | None = None,
        on_call=None,
    ) -> None:
        self.dimension = dimension
        self.bad_call_index = bad_call_index
        self.on_call = on_call
        self.calls: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        dimension = self.dimension
        if self.bad_call_index == len(self.calls):
            dimension -= 1
        vectors = [[float(len(self.calls))] * dimension for _ in texts]
        if self.on_call is not None:
            self.on_call(len(self.calls), list(texts))
        return vectors


def _replace_with_current_adaptive_children(session, tenant_id, document_id, job_id):
    from server.app.models.qa_pair import DocumentChunk

    existing = session.scalars(
        select(DocumentChunk).where(DocumentChunk.document_id == document_id)
    ).all()
    for chunk in existing:
        chunk.status = "SUPERSEDED"

    parent = DocumentChunk(
        tenant_id=tenant_id,
        document_id=document_id,
        job_id=job_id,
        chunk_index=0,
        content="退款流程和发票处理。",
        page_no=1,
        page_start=1,
        page_end=2,
        title_path=["退款流程"],
        source_locator={"lineStart": 1},
        block_type="TEXT",
        chunk_level="PARENT",
        chunker_name="adaptive_hierarchical",
        chunker_version="1.1",
        chunker_config_hash="current-generation",
        status="ACTIVE",
    )
    session.add(parent)
    session.flush()
    children = [
        DocumentChunk(
            tenant_id=tenant_id,
            document_id=document_id,
            job_id=job_id,
            chunk_index=0,
            content="退款需要主管审批。",
            page_no=1,
            page_start=1,
            page_end=1,
            title_path=["退款流程"],
            source_locator={"lineStart": 1},
            block_type="TEXT",
            chunk_level="CHILD",
            parent_chunk_id=parent.id,
            chunker_name="adaptive_hierarchical",
            chunker_version="1.1",
            chunker_config_hash="current-generation",
            status="ACTIVE",
        ),
        DocumentChunk(
            tenant_id=tenant_id,
            document_id=document_id,
            job_id=job_id,
            chunk_index=1,
            content="已开票订单需先红冲发票。",
            page_no=2,
            page_start=2,
            page_end=2,
            title_path=["退款流程", "发票处理"],
            source_locator={"lineStart": 4},
            block_type="TABLE",
            chunk_level="CHILD",
            parent_chunk_id=parent.id,
            chunker_name="adaptive_hierarchical",
            chunker_version="1.1",
            chunker_config_hash="current-generation",
            status="ACTIVE",
        ),
        DocumentChunk(
            tenant_id=tenant_id,
            document_id=document_id,
            job_id=job_id,
            chunk_index=99,
            content="旧 generation 不得被索引。",
            page_no=3,
            title_path=["旧版本"],
            source_locator={"lineStart": 99},
            block_type="TEXT",
            chunk_level="CHILD",
            chunker_name="adaptive_hierarchical",
            chunker_version="1.0",
            chunker_config_hash="old-generation",
            status="SUPERSEDED",
        ),
    ]
    session.add_all(children)
    session.commit()
    return parent, children


def _prepare_adaptive_embedding_job(session, identity):
    tenant_id = identity["tenant"].id
    job_id, document_id, _ = prepare_embedding_job(session, identity)
    parent, children = _replace_with_current_adaptive_children(
        session, tenant_id, document_id, job_id
    )
    pairs = add_qa_pairs(session, tenant_id, document_id, job_id, [item.id for item in children])
    from server.app.models.import_job import ImportJob

    job = session.get(ImportJob, job_id)
    job.options = {"embedding": {"run_config_hash": "current-generation"}}
    session.commit()
    return tenant_id, job_id, document_id, parent, children, pairs


def test_embedding_indexes_qa_and_current_active_child_chunks_separately():
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.qa_pair import DocumentChunk, QaPair
    from server.app.services.embedding_service import EmbeddingService

    session, identity = build_qa_session()
    tenant_id, job_id, document_id, parent, children, _ = _prepare_adaptive_embedding_job(
        session, identity
    )
    add_default_embedding_model(session, tenant_id, expected_dimension=4)
    adapter = _RecordingEmbeddingAdapter()

    result = EmbeddingService(
        session,
        provider_factory=lambda *_args, **_kwargs: adapter,
        chunk_indexing_enabled=True,
    ).embed_import_job(job_id)

    document = session.get(Document, document_id)
    qa_pairs = session.scalars(
        select(QaPair).where(QaPair.document_id == document_id).order_by(QaPair.pair_index)
    ).all()
    persisted_children = session.scalars(
        select(DocumentChunk)
        .where(
            DocumentChunk.id.in_([item.id for item in children]),
            DocumentChunk.status == "ACTIVE",
        )
        .order_by(DocumentChunk.chunk_index)
    ).all()
    persisted_parent = session.get(DocumentChunk, parent.id)

    assert result.status == "COMPLETED"
    assert document.status == DocumentStatus.READY
    assert len(adapter.calls) == 2
    assert adapter.calls[0] == [item.question for item in qa_pairs]
    assert adapter.calls[1] == [
        "文档：Refund SOP\n章节：退款流程\n类型：TEXT\n正文：退款需要主管审批。",
        "文档：Refund SOP\n章节：退款流程 / 发票处理\n类型：TABLE\n正文：已开票订单需先红冲发票。",
    ]
    assert all(item.question_embedding is not None for item in qa_pairs)
    assert all(item.embedding is not None for item in persisted_children)
    qa_embedding_metadata = qa_pairs[0].qa_metadata["embedding"]
    assert qa_embedding_metadata["targetType"] == "QA"
    assert qa_embedding_metadata["embeddingTemplateVersion"] == "qa-question-v1"
    assert qa_embedding_metadata["inputTextHash"] == sha256(
        qa_pairs[0].question.encode("utf-8")
    ).hexdigest()
    chunk_embedding_metadata = persisted_children[0].chunk_metadata["embedding"]
    assert chunk_embedding_metadata["targetType"] == "CHUNK"
    assert (
        chunk_embedding_metadata["embeddingTemplateVersion"]
        == "chunk-document-title-path-type-content-v1"
    )
    assert chunk_embedding_metadata["inputTextHash"] == sha256(
        adapter.calls[1][0].encode("utf-8")
    ).hexdigest()
    assert persisted_parent.embedding is None
    assert persisted_parent.search_text == ""
    assert all("refund" in item.search_text for item in qa_pairs)
    assert "退款 流程" in qa_pairs[0].search_text
    assert "refund" in persisted_children[0].search_text
    assert "退款 流程" in persisted_children[0].search_text
    assert "退款 需要 主管 审批" in persisted_children[0].search_text


def test_chunk_embedding_only_processes_missing_or_stale_current_generation_children():
    from server.app.models.document import Document
    from server.app.models.qa_pair import DocumentChunk
    from server.app.services.embedding_service import (
        CHUNK_EMBEDDING_TEMPLATE_VERSION,
        EmbeddingService,
        build_chunk_embedding_text,
        build_chunk_search_text,
    )

    session, identity = build_qa_session()
    tenant_id, job_id, document_id, _parent, children, _ = _prepare_adaptive_embedding_job(
        session, identity
    )
    add_default_embedding_model(session, tenant_id, expected_dimension=4)
    adapter = _RecordingEmbeddingAdapter()
    service = EmbeddingService(
        session,
        provider_factory=lambda *_args, **_kwargs: adapter,
        chunk_indexing_enabled=True,
    )
    model, provider = service._default_model(tenant_id)
    model_key = service._model_key(model, provider, 4)
    document = session.get(Document, document_id)
    children[0].embedding = [9.0] * 4
    children[0].search_text = build_chunk_search_text(
        service.tokenizer, document, children[0]
    )
    children[0].chunk_metadata = {
        "embedding": {
            "targetType": "CHUNK",
            "embeddingTemplateVersion": CHUNK_EMBEDDING_TEMPLATE_VERSION,
            "inputTextHash": sha256(
                build_chunk_embedding_text(document, children[0]).encode("utf-8")
            ).hexdigest(),
            "modelKey": model_key,
        }
    }
    children[1].embedding = [8.0] * 4
    children[1].search_text = build_chunk_search_text(
        service.tokenizer, document, children[1]
    )
    children[1].chunk_metadata = {"embedding": {"modelKey": "stale-model"}}
    session.commit()

    result = service.embed_import_job(job_id)

    persisted = session.scalars(
        select(DocumentChunk)
        .where(DocumentChunk.id.in_([children[0].id, children[1].id]))
        .order_by(DocumentChunk.chunk_index)
    ).all()
    assert result.status == "COMPLETED"
    assert len(adapter.calls) == 2
    assert adapter.calls[1] == [
        "文档：Refund SOP\n章节：退款流程 / 发票处理\n类型：TABLE\n正文：已开票订单需先红冲发票。"
    ]
    assert persisted[0].embedding == [9.0] * 4
    assert persisted[1].embedding == [2.0] * 4




def test_adaptive_embedding_excludes_qa_pairs_from_superseded_source_children():
    from server.app.models.qa_pair import QaPair
    from server.app.services.embedding_service import EmbeddingService

    session, identity = build_qa_session()
    tenant_id, job_id, document_id, _parent, children, _ = _prepare_adaptive_embedding_job(
        session, identity
    )
    add_default_embedding_model(session, tenant_id, expected_dimension=4)
    superseded_pair = QaPair(
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_id=children[2].id,
        job_id=job_id,
        pair_index=99,
        question="旧 generation 的 QA 不得被索引。",
        answer="这是已被替换的来源。",
        search_text="",
        status="ACTIVE",
    )
    session.add(superseded_pair)
    session.commit()
    adapter = _RecordingEmbeddingAdapter()

    result = EmbeddingService(
        session,
        provider_factory=lambda *_args, **_kwargs: adapter,
        chunk_indexing_enabled=True,
    ).embed_import_job(job_id)

    session.refresh(superseded_pair)
    assert result.status == "COMPLETED"
    assert adapter.calls[0] == ["退款需要谁审批？", "已开票订单退款前要做什么？"]
    assert superseded_pair.question_embedding is None


def test_adaptive_embedding_rejects_generation_switch_without_persisting_vectors():
    from server.app.models.document import Document
    from server.app.models.logs import TaskRun
    from server.app.models.qa_pair import DocumentChunk, QaPair
    from server.app.services.embedding_service import EmbeddingService

    session, identity = build_qa_session()
    tenant_id, job_id, document_id, _parent, children, _ = _prepare_adaptive_embedding_job(
        session, identity
    )
    add_default_embedding_model(session, tenant_id, expected_dimension=4)

    def switch_generation_after_chunk_call(call_index, _texts):
        if call_index != 2:
            return
        for chunk in session.scalars(
            select(DocumentChunk).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.status == "ACTIVE",
            )
        ):
            chunk.status = "SUPERSEDED"
        replacement_parent = DocumentChunk(
            tenant_id=tenant_id,
            document_id=document_id,
            job_id=job_id,
            chunk_index=0,
            content="替换 generation 的父块。",
            title_path=["替换版本"],
            block_type="TEXT",
            chunk_level="PARENT",
            chunker_name="adaptive_hierarchical",
            chunker_version="1.1",
            chunker_config_hash="replacement-generation",
            status="ACTIVE",
        )
        session.add(replacement_parent)
        session.flush()
        session.add(
            DocumentChunk(
                tenant_id=tenant_id,
                document_id=document_id,
                job_id=job_id,
                chunk_index=0,
                content="替换 generation 的子块。",
                title_path=["替换版本"],
                block_type="TEXT",
                chunk_level="CHILD",
                parent_chunk_id=replacement_parent.id,
                chunker_name="adaptive_hierarchical",
                chunker_version="1.1",
                chunker_config_hash="replacement-generation",
                status="ACTIVE",
            )
        )
        session.flush()

    adapter = _RecordingEmbeddingAdapter(on_call=switch_generation_after_chunk_call)
    result = EmbeddingService(
        session,
        provider_factory=lambda *_args, **_kwargs: adapter,
        chunk_indexing_enabled=True,
    ).embed_import_job(job_id)

    qa_pairs = session.scalars(
        select(QaPair).where(QaPair.document_id == document_id).order_by(QaPair.pair_index)
    ).all()
    persisted_children = session.scalars(
        select(DocumentChunk).where(DocumentChunk.id.in_([item.id for item in children]))
    ).all()
    document = session.get(Document, document_id)
    task_run = session.scalars(
        select(TaskRun)
        .where(TaskRun.resource_id == job_id)
        .order_by(TaskRun.created_at.desc())
    ).first()

    assert result.status == "FAILED"
    assert document.last_error_code == "EMBEDDING_RUN_CONFIG_CHANGED"
    assert task_run.error["retryable"] is True
    assert all(item.question_embedding is None for item in qa_pairs)
    assert all(item.embedding is None for item in persisted_children)



def test_pre_final_check_generation_switch_does_not_persist_old_vectors(
    tmp_path, monkeypatch
):
    """A pre-final-check generation switch must reject stale vectors on SQLite.

    SQLite does not implement PostgreSQL row-lock semantics for ``FOR UPDATE``.
    This regression injects a replacement generation immediately before the
    service's final locked-query validation and verifies that the revalidation
    rejects the stale QA/Child target set.  It intentionally does not claim to
    validate cross-session row-lock behavior; that evidence lives in the
    PostgreSQL integration regression below.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from server.app.db.base import Base
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.qa_pair import DocumentChunk, QaPair
    from server.app.services.embedding_service import EmbeddingService
    from server.app.services.seed_service import seed_identity_data

    database_path = tmp_path / "embedding-final-lock-race.sqlite"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    identity = seed_identity_data(session)
    tenant_id, job_id, document_id, _parent, children, _ = _prepare_adaptive_embedding_job(
        session, identity
    )
    add_default_embedding_model(session, tenant_id, expected_dimension=4)
    adapter = _RecordingEmbeddingAdapter()
    service = EmbeddingService(
        session,
        provider_factory=lambda *_args, **_kwargs: adapter,
        chunk_indexing_enabled=True,
    )

    original_scalar = session.scalar
    replacement_committed = False

    def replace_active_generation_in_parse_transaction():
        nonlocal replacement_committed
        with SessionLocal() as parse_session:
            active_chunks = parse_session.scalars(
                select(DocumentChunk).where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.status == "ACTIVE",
                )
            ).all()
            for chunk in active_chunks:
                chunk.status = "SUPERSEDED"
            parent = DocumentChunk(
                tenant_id=tenant_id,
                document_id=document_id,
                job_id=job_id,
                chunk_index=0,
                content="替换 generation 的父块。",
                title_path=["替换版本"],
                block_type="TEXT",
                chunk_level="PARENT",
                chunker_name="adaptive_hierarchical",
                chunker_version="1.1",
                chunker_config_hash="replacement-generation",
                status="ACTIVE",
            )
            parse_session.add(parent)
            parse_session.flush()
            parse_session.add(
                DocumentChunk(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    job_id=job_id,
                    chunk_index=0,
                    content="替换 generation 的子块。",
                    title_path=["替换版本"],
                    block_type="TEXT",
                    chunk_level="CHILD",
                    parent_chunk_id=parent.id,
                    chunker_name="adaptive_hierarchical",
                    chunker_version="1.1",
                    chunker_config_hash="replacement-generation",
                    status="ACTIVE",
                )
            )
            parse_session.commit()
        replacement_committed = True

    def scalar_at_final_lock(statement, *args, **kwargs):
        if (
            not replacement_committed
            and getattr(statement, "_for_update_arg", None) is not None
        ):
            replace_active_generation_in_parse_transaction()
        return original_scalar(statement, *args, **kwargs)

    monkeypatch.setattr(session, "scalar", scalar_at_final_lock)
    result = service.embed_import_job(job_id)

    qa_pairs = session.scalars(
        select(QaPair).where(QaPair.document_id == document_id).order_by(QaPair.pair_index)
    ).all()
    old_children = session.scalars(
        select(DocumentChunk).where(DocumentChunk.id.in_([item.id for item in children]))
    ).all()
    document = session.get(Document, document_id)

    assert replacement_committed is True
    assert len(adapter.calls) == 2
    assert result.status == "FAILED"
    assert document.status == DocumentStatus.FAILED
    assert document.last_error_code == "EMBEDDING_RUN_CONFIG_CHANGED"
    assert all(pair.question_embedding is None for pair in qa_pairs)
    assert all(chunk.embedding is None for chunk in old_children)

def test_adaptive_embedding_reembeds_when_input_hash_or_template_version_is_stale():
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob, ImportJobStatus
    from server.app.models.qa_pair import DocumentChunk, QaPair
    from server.app.services.embedding_service import (
        EmbeddingService,
        build_chunk_search_text,
        build_search_text,
    )

    session, identity = build_qa_session()
    tenant_id, job_id, document_id, _parent, children, _ = _prepare_adaptive_embedding_job(
        session, identity
    )
    add_default_embedding_model(session, tenant_id, expected_dimension=4)
    first_adapter = _RecordingEmbeddingAdapter()
    service = EmbeddingService(
        session,
        provider_factory=lambda *_args, **_kwargs: first_adapter,
        chunk_indexing_enabled=True,
    )
    assert service.embed_import_job(job_id).status == "COMPLETED"

    document = session.get(Document, document_id)
    job = session.get(ImportJob, job_id)
    qa_pair = session.scalars(
        select(QaPair)
        .where(QaPair.document_id == document_id, QaPair.pair_index == 0)
    ).one()
    child = session.get(DocumentChunk, children[0].id)
    qa_pair.question = "退款需要哪位主管审批？"
    child.content = "退款需要财务主管审批。"
    qa_pair.search_text = build_search_text(service.tokenizer, qa_pair, document, child)
    child.search_text = build_chunk_search_text(service.tokenizer, document, child)
    document.status = DocumentStatus.EMBEDDING
    job.status = ImportJobStatus.RUNNING.value
    job.stage = "EMBEDDING"
    session.commit()

    changed_adapter = _RecordingEmbeddingAdapter()
    changed_result = EmbeddingService(
        session,
        provider_factory=lambda *_args, **_kwargs: changed_adapter,
        chunk_indexing_enabled=True,
    ).embed_import_job(job_id)

    assert changed_result.status == "COMPLETED"
    assert changed_adapter.calls == [
        ["退款需要哪位主管审批？"],
        ["文档：Refund SOP\n章节：退款流程\n类型：TEXT\n正文：退款需要财务主管审批。"],
    ]
    assert qa_pair.qa_metadata["embedding"]["inputTextHash"] == sha256(
        qa_pair.question.encode("utf-8")
    ).hexdigest()
    assert child.chunk_metadata["embedding"]["inputTextHash"] == sha256(
        changed_adapter.calls[1][0].encode("utf-8")
    ).hexdigest()

    qa_pair.qa_metadata = {
        **qa_pair.qa_metadata,
        "embedding": {
            **qa_pair.qa_metadata["embedding"],
            "embeddingTemplateVersion": "obsolete",
        },
    }
    child.chunk_metadata = {
        **child.chunk_metadata,
        "embedding": {
            **child.chunk_metadata["embedding"],
            "embeddingTemplateVersion": "obsolete",
        },
    }
    document.status = DocumentStatus.EMBEDDING
    job.status = ImportJobStatus.RUNNING.value
    job.stage = "EMBEDDING"
    session.commit()

    template_adapter = _RecordingEmbeddingAdapter()
    template_result = EmbeddingService(
        session,
        provider_factory=lambda *_args, **_kwargs: template_adapter,
        chunk_indexing_enabled=True,
    ).embed_import_job(job_id)

    assert template_result.status == "COMPLETED"
    assert template_adapter.calls == [
        [qa_pair.question],
        ["文档：Refund SOP\n章节：退款流程\n类型：TEXT\n正文：退款需要财务主管审批。"],
    ]

def test_chunk_embedding_dimension_failure_does_not_partially_persist_qa_or_children():
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.qa_pair import DocumentChunk, QaPair
    from server.app.services.embedding_service import EmbeddingService

    session, identity = build_qa_session()
    tenant_id, job_id, document_id, _parent, children, _ = _prepare_adaptive_embedding_job(
        session, identity
    )
    add_default_embedding_model(session, tenant_id, expected_dimension=4)
    adapter = _RecordingEmbeddingAdapter(bad_call_index=2)

    result = EmbeddingService(
        session,
        provider_factory=lambda *_args, **_kwargs: adapter,
        chunk_indexing_enabled=True,
    ).embed_import_job(job_id)

    qa_pairs = session.scalars(
        select(QaPair).where(QaPair.document_id == document_id).order_by(QaPair.pair_index)
    ).all()
    persisted_children = session.scalars(
        select(DocumentChunk).where(DocumentChunk.id.in_([item.id for item in children]))
    ).all()
    document = session.get(Document, document_id)

    assert result.status == "FAILED"
    assert document.status == DocumentStatus.FAILED
    assert document.last_error_code == "EMBEDDING_DIMENSION_MISMATCH"
    assert len(adapter.calls) == 2
    assert all(item.question_embedding is None for item in qa_pairs)
    assert all(item.embedding is None for item in persisted_children)
    assert all(item.status == "EMBEDDING_FAILED" for item in qa_pairs)


def test_chunk_indexing_disabled_keeps_qa_only_completion_semantics():
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.qa_pair import DocumentChunk, QaPair
    from server.app.services.embedding_service import EmbeddingService

    session, identity = build_qa_session()
    tenant_id, job_id, document_id, _parent, children, _ = _prepare_adaptive_embedding_job(
        session, identity
    )
    add_default_embedding_model(session, tenant_id, expected_dimension=4)
    adapter = _RecordingEmbeddingAdapter()

    result = EmbeddingService(
        session,
        provider_factory=lambda *_args, **_kwargs: adapter,
        chunk_indexing_enabled=False,
    ).embed_import_job(job_id)

    document = session.get(Document, document_id)
    qa_pairs = session.scalars(select(QaPair).where(QaPair.document_id == document_id)).all()
    persisted_children = session.scalars(
        select(DocumentChunk).where(DocumentChunk.id.in_([item.id for item in children]))
    ).all()

    assert result.status == "COMPLETED"
    assert document.status == DocumentStatus.READY
    assert len(adapter.calls) == 1
    assert all(item.question_embedding is not None for item in qa_pairs)
    assert all(item.embedding is None for item in persisted_children)


def test_embedding_rejects_input_larger_than_model_limit_before_provider_call():
    from server.app.models.qa_pair import DocumentChunk, QaPair
    from server.app.services.embedding_service import EmbeddingService

    session, identity = build_qa_session()
    tenant_id, job_id, document_id, _parent, children, _ = _prepare_adaptive_embedding_job(
        session, identity
    )
    model = add_default_embedding_model(session, tenant_id, expected_dimension=4)
    model.max_tokens = 1
    session.commit()
    adapter = _RecordingEmbeddingAdapter()

    result = EmbeddingService(
        session,
        provider_factory=lambda *_args, **_kwargs: adapter,
        chunk_indexing_enabled=True,
    ).embed_import_job(job_id)

    qa_pairs = session.scalars(select(QaPair).where(QaPair.document_id == document_id)).all()
    persisted_children = session.scalars(
        select(DocumentChunk).where(DocumentChunk.id.in_([item.id for item in children]))
    ).all()
    assert result.status == "FAILED"
    assert result.error_code == "EMBEDDING_INPUT_TOO_LONG"
    assert adapter.calls == []
    assert all(item.question_embedding is None for item in qa_pairs)
    assert all(item.embedding is None for item in persisted_children)


def _postgresql_lock_test_url() -> str | None:
    """Return the explicit, isolated PostgreSQL integration-test URL only."""
    import os

    url = os.getenv("LINGXI_TEST_POSTGRES_URL")
    if not url:
        return None
    from sqlalchemy.engine import make_url

    return url if make_url(url).get_backend_name() == "postgresql" else None


def test_postgresql_final_document_lock_blocks_generation_switch_until_embedding_commit():
    """PostgreSQL must hold Document FOR UPDATE through vectors and terminal state.

    The embedding worker reaches its *post-provider* final ``Document FOR
    UPDATE`` and pauses while holding it.  A distinct parser transaction then
    attempts DocumentParseService's same lock before replacing the active
    generation.  The parser cannot acquire that lock until embedding persists
    QA/Child vectors and commits READY/COMPLETED/SUCCESS.  Its snapshot after
    acquiring the lock proves those terminal writes were included in the
    lock-held transaction, before it is allowed to switch the generation.
    """
    import queue
    import threading
    from uuid import uuid4

    import pytest
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.orm import sessionmaker

    from server.app.db.base import Base
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.import_job import ImportJob, ImportJobStatus
    from server.app.models.logs import TaskRun
    from server.app.models.qa_pair import DocumentChunk, QaPair
    from server.app.services.embedding_service import EmbeddingService
    from server.app.services.seed_service import seed_identity_data

    url = _postgresql_lock_test_url()
    if url is None:
        pytest.skip("requires LINGXI_TEST_POSTGRES_URL for PostgreSQL lock integration")

    schema = f"task12_embedding_lock_{uuid4().hex}"
    admin_engine = create_engine(url, pool_pre_ping=True)
    test_engine = None
    setup_session = None
    embedding_session = None
    verify_session = None
    switch_session = None
    embedding_thread = None
    switch_thread = None
    embedding_may_commit = threading.Event()
    final_document_lock_acquired = threading.Event()
    switch_lock_attempted = threading.Event()
    switch_document_lock_acquired = threading.Event()
    switch_terminal_state_observed = threading.Event()
    allow_generation_switch = threading.Event()
    worker_errors: queue.Queue[BaseException] = queue.Queue()
    switch_observed_terminal_state: list[bool] = []

    try:
        with admin_engine.begin() as connection:
            # PgVector columns in the real model require the extension; the CI
            # service uses a pgvector image, so inability to enable it is a test
            # environment error rather than a silent SQLite fallback.
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))

        test_engine = create_engine(
            url,
            connect_args={"options": f"-csearch_path={schema},public"},
            pool_size=4,
            max_overflow=0,
            pool_pre_ping=True,
        )
        SessionLocal = sessionmaker(
            bind=test_engine,
            autoflush=False,
            autocommit=False,
        )
        # SQLAlchemy's PostgreSQL ``checkfirst`` sees public tables through the
        # search path.  Force DDL in this unique schema so the regression never
        # reads or mutates the application schema.
        Base.metadata.create_all(bind=test_engine, checkfirst=False)

        setup_session = SessionLocal()
        identity = seed_identity_data(setup_session)
        tenant_id, job_id, document_id, _parent, children, _ = _prepare_adaptive_embedding_job(
            setup_session, identity
        )
        add_default_embedding_model(setup_session, tenant_id, expected_dimension=1024)
        setup_session.commit()
        expected_child_ids = {child.id for child in children if child.status == "ACTIVE"}
        setup_session.close()
        setup_session = None

        class _SignallingEmbeddingService(EmbeddingService):
            def _lock_document_for_embedding_commit(self, locked_document_id: str):
                document = super()._lock_document_for_embedding_commit(locked_document_id)
                final_document_lock_acquired.set()
                if not embedding_may_commit.wait(timeout=10):
                    raise TimeoutError("test did not release embedding terminal commit")
                return document

        embedding_session = SessionLocal()
        switch_session = SessionLocal()

        def embed_worker() -> None:
            try:
                result = _SignallingEmbeddingService(
                    embedding_session,
                    provider_factory=lambda *_args, **_kwargs: _RecordingEmbeddingAdapter(dimension=1024),
                    chunk_indexing_enabled=True,
                ).embed_import_job(job_id)
                if result.status != "COMPLETED":
                    raise AssertionError(f"embedding result was {result.status}, expected COMPLETED")
            except BaseException as exc:  # propagate cross-thread failures to pytest
                worker_errors.put(exc)

        def switch_active_generation_after_document_lock() -> None:
            try:
                switch_lock_attempted.set()
                # This is the same Document row lock used by DocumentParseService
                # before it makes its active-generation decision.
                switch_document = switch_session.scalar(
                    select(Document)
                    .where(Document.id == document_id)
                    .with_for_update()
                )
                if switch_document is None:
                    raise AssertionError("switch transaction could not load document")
                switch_document_lock_acquired.set()

                current_job = switch_session.get(ImportJob, job_id)
                current_task_run = switch_session.scalars(
                    select(TaskRun)
                    .where(TaskRun.resource_id == job_id)
                    .order_by(TaskRun.created_at.desc())
                ).first()
                switch_observed_terminal_state.append(
                    switch_document.status == DocumentStatus.READY
                    and current_job is not None
                    and current_job.status == ImportJobStatus.COMPLETED.value
                    and current_job.stage == "COMPLETED"
                    and current_task_run is not None
                    and current_task_run.status == "SUCCESS"
                )
                switch_terminal_state_observed.set()

                if not allow_generation_switch.wait(timeout=10):
                    raise TimeoutError("test did not release parser generation switch")

                active_chunks = switch_session.scalars(
                    select(DocumentChunk).where(
                        DocumentChunk.document_id == document_id,
                        DocumentChunk.status == "ACTIVE",
                    )
                ).all()
                for chunk in active_chunks:
                    chunk.status = "SUPERSEDED"
                replacement_parent = DocumentChunk(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    job_id=job_id,
                    chunk_index=0,
                    content="PostgreSQL replacement parent.",
                    title_path=["Replacement"],
                    block_type="TEXT",
                    chunk_level="PARENT",
                    chunker_name="adaptive_hierarchical",
                    chunker_version="1.1",
                    chunker_config_hash="postgres-replacement-generation",
                    status="ACTIVE",
                )
                switch_session.add(replacement_parent)
                switch_session.flush()
                switch_session.add(
                    DocumentChunk(
                        tenant_id=tenant_id,
                        document_id=document_id,
                        job_id=job_id,
                        chunk_index=0,
                        content="PostgreSQL replacement child.",
                        title_path=["Replacement"],
                        block_type="TEXT",
                        chunk_level="CHILD",
                        parent_chunk_id=replacement_parent.id,
                        chunker_name="adaptive_hierarchical",
                        chunker_version="1.1",
                        chunker_config_hash="postgres-replacement-generation",
                        status="ACTIVE",
                    )
                )
                switch_session.commit()
            except BaseException as exc:  # propagate cross-thread failures to pytest
                switch_session.rollback()
                worker_errors.put(exc)

        embedding_thread = threading.Thread(target=embed_worker, name="embedding-worker")
        embedding_thread.start()
        if not final_document_lock_acquired.wait(timeout=10):
            embedding_thread.join(timeout=1)
            if not worker_errors.empty():
                raise worker_errors.get()
            pytest.fail("embedding worker never reached its post-provider Document FOR UPDATE")

        switch_thread = threading.Thread(
            target=switch_active_generation_after_document_lock,
            name="parser-generation-switch",
        )
        switch_thread.start()
        assert switch_lock_attempted.wait(timeout=5)
        # A PostgreSQL SELECT FOR UPDATE in a different session must remain
        # blocked while embedding owns the Document lock; this is intentionally
        # not inferred from SQLite behavior.
        assert not switch_document_lock_acquired.wait(timeout=0.35)

        embedding_may_commit.set()
        embedding_thread.join(timeout=10)
        assert not embedding_thread.is_alive()
        if not worker_errors.empty():
            raise worker_errors.get()

        assert switch_document_lock_acquired.wait(timeout=10), (
            "parser transaction did not acquire Document lock after embedding commit"
        )
        assert switch_terminal_state_observed.wait(timeout=5)
        assert switch_observed_terminal_state == [True]

        # Hold the parser after it owns the lock so this independent verification
        # observes exactly the committed embedding generation, not a later switch.
        verify_session = SessionLocal()
        document = verify_session.get(Document, document_id)
        job = verify_session.get(ImportJob, job_id)
        task_run = verify_session.scalars(
            select(TaskRun)
            .where(TaskRun.resource_id == job_id)
            .order_by(TaskRun.created_at.desc())
        ).first()
        qa_pairs = verify_session.scalars(
            select(QaPair).where(QaPair.document_id == document_id).order_by(QaPair.pair_index)
        ).all()
        active_children = verify_session.scalars(
            select(DocumentChunk).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.status == "ACTIVE",
                DocumentChunk.chunk_level == "CHILD",
            )
        ).all()

        assert document.status == DocumentStatus.READY
        assert job.status == ImportJobStatus.COMPLETED.value
        assert job.stage == "COMPLETED"
        assert task_run is not None and task_run.status == "SUCCESS"
        assert all(pair.question_embedding is not None for pair in qa_pairs)
        assert {child.id for child in active_children} == expected_child_ids
        assert {child.chunker_config_hash for child in active_children} == {"current-generation"}
        assert all(child.embedding is not None for child in active_children)

        allow_generation_switch.set()
        switch_thread.join(timeout=10)
        assert not switch_thread.is_alive()
        if not worker_errors.empty():
            raise worker_errors.get()

        verify_session.expire_all()
        final_active_children = verify_session.scalars(
            select(DocumentChunk).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.status == "ACTIVE",
                DocumentChunk.chunk_level == "CHILD",
            )
        ).all()
        assert len(final_active_children) == 1
        assert final_active_children[0].chunker_config_hash == "postgres-replacement-generation"
        assert final_active_children[0].embedding is None
    finally:
        embedding_may_commit.set()
        allow_generation_switch.set()
        for thread in (embedding_thread, switch_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=10)
        for session in (verify_session, switch_session, embedding_session, setup_session):
            if session is not None:
                session.close()
        if test_engine is not None:
            test_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
