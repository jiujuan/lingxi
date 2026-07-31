import json

import pytest
from sqlalchemy import select

from server.app.models.qa_pair import DocumentChunk


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

    for payload, expected_code in [
        ("not-json", "QA_SPLIT_INVALID_OUTPUT"),
        ('{"items":[{"question":"缺少答案"}]}', "QA_PROVENANCE_CONTRACT_INVALID"),
    ]:
        try:
            validate_qa_split_output(payload)
        except QaSplitValidationError as exc:
            assert exc.code == expected_code
        else:
            raise AssertionError("invalid QA output should fail validation")


def test_qa_split_service_writes_pairs_and_is_idempotent():
    session, identity = build_qa_session()
    tenant_id = identity["tenant"].id
    job_id, document_id, chunks = create_qa_ready_job(session, identity)
    add_default_qa_model(
        session,
        tenant_id,
        _strict_qa_payload(
            items=[
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
            ],
            covered=[0, 1],
            skipped=[],
        ),
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
    assert job.options["embedding"]["run_config_hash"] == chunks[0].chunker_config_hash


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
            _strict_qa_payload(
                items=[
                    {
                        "question": "退款怎么审批？",
                        "answer": "由主管审批。",
                        "quote": "退款需要主管审批。",
                        "pageNo": 1,
                        "chunkIndex": 0,
                    }
                ],
                covered=[0],
                skipped=[{"chunkIndex": 1, "reason": "本片段未生成 QA"}],
            ),
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



def _strict_qa_payload(*, items, covered, skipped):
    return {
        "items": items,
        "coveredChunkIndexes": covered,
        "skippedChunks": skipped,
    }


def test_qa_prompt_requires_complete_batch_coverage_contract():
    from server.app.models.document import Document
    from server.app.models.qa_pair import DocumentChunk
    from server.app.services.qa_prompt_builder import build_qa_split_prompt

    document = Document(title="Refund SOP")
    chunks = [
        DocumentChunk(chunk_index=7, content="退款需要主管审批。", page_no=1),
        DocumentChunk(chunk_index=12, content="已开票订单需先红冲发票。", page_no=2),
    ]

    prompt = build_qa_split_prompt(document, chunks)

    assert '"coveredChunkIndexes"' in prompt
    assert '"skippedChunks"' in prompt
    assert '"chunkIndex"' in prompt
    assert "完备分区" in prompt
    assert "不能同时" in prompt


def test_strict_adaptive_output_rejects_missing_provenance_without_writing_pairs():
    session, identity = build_qa_session()
    tenant_id = identity["tenant"].id
    job_id, document_id, chunks = create_qa_ready_job(session, identity)
    for chunk in chunks:
        chunk.chunker_name = "adaptive_hierarchical"
        chunk.chunker_version = "1.0"
        chunk.chunker_config_hash = "adaptive-generation"
    session.commit()
    add_default_qa_model(
        session,
        tenant_id,
        {"items": [{
            "question": "退款需要谁审批？",
            "answer": "退款需要主管审批。",
            "quote": "退款需要主管审批。",
            "pageNo": 1,
        }]},
    )

    from server.app.models.document import Document, DocumentStatus
    from server.app.models.qa_pair import QaPair
    from server.app.services.qa_split_service import QaSplitService

    result = QaSplitService(session).split_import_job(job_id)

    assert result.status == "FAILED"
    assert session.get(Document, document_id).status == DocumentStatus.FAILED
    assert session.scalars(select(QaPair).where(QaPair.document_id == document_id)).all() == []


@pytest.mark.parametrize(
    "payload",
    [
        _strict_qa_payload(
            items=[{
                "question": "退款需要谁审批？",
                "answer": "退款需要主管审批。",
                "quote": "退款需要主管审批。",
                "pageNo": 1,
                "chunkIndex": 99,
            }],
            covered=[0],
            skipped=[{"chunkIndex": 1, "reason": "没有可生成的问题"}],
        ),
        _strict_qa_payload(
            items=[{
                "question": "退款需要谁审批？",
                "answer": "退款需要主管审批。",
                "quote": "不属于片段的引用。",
                "pageNo": 1,
                "chunkIndex": 0,
            }],
            covered=[0],
            skipped=[{"chunkIndex": 1, "reason": "没有可生成的问题"}],
        ),
        _strict_qa_payload(
            items=[{
                "question": "退款需要谁审批？",
                "answer": "退款需要主管审批。",
                "quote": "退款需要主管审批。",
                "pageNo": 3,
                "chunkIndex": 0,
            }],
            covered=[0],
            skipped=[{"chunkIndex": 1, "reason": "没有可生成的问题"}],
        ),
        _strict_qa_payload(
            items=[{
                "question": "退款需要谁审批？",
                "answer": "退款需要主管审批。",
                "quote": "退款需要主管审批。",
                "pageNo": 1,
                "chunkIndex": 0,
            }],
            covered=[0],
            skipped=[],
        ),
    ],
)
def test_strict_validator_rejects_unknown_quote_page_and_incomplete_coverage(payload):
    from server.app.models.qa_pair import DocumentChunk
    from server.app.services.qa_split_service import (
        QaSplitValidationError,
        validate_qa_split_output,
    )

    chunks = [
        DocumentChunk(
            chunk_index=0,
            content="退款需要主管审批。",
            page_no=1,
            page_start=1,
            page_end=1,
        ),
        DocumentChunk(
            chunk_index=1,
            content="已开票订单需先红冲发票。",
            page_no=2,
            page_start=2,
            page_end=2,
        ),
    ]

    with pytest.raises(QaSplitValidationError):
        validate_qa_split_output(json.dumps(payload), chunks)


def test_strict_validator_normalizes_quote_containment_but_preserves_original_quote():
    from server.app.models.qa_pair import DocumentChunk
    from server.app.services.qa_split_service import validate_qa_split_output

    quote = "Cafe\u0301\n  policy"
    chunks = [
        DocumentChunk(
            chunk_index=4,
            content="Caf\u00e9 policy must be followed.",
            page_no=3,
            page_start=3,
            page_end=3,
        )
    ]
    payload = _strict_qa_payload(
        items=[{
            "question": "What applies?",
            "answer": "The policy applies.",
            "quote": quote,
            "pageNo": 3,
            "chunkIndex": 4,
        }],
        covered=[4],
        skipped=[],
    )

    validated = validate_qa_split_output(json.dumps(payload), chunks)

    assert validated[0].quote == quote
    assert validated[0].chunk_index == 4


def test_legacy_compatibility_missing_index_never_uses_first_chunk_fallback():
    from server.app.models.qa_pair import DocumentChunk
    from server.app.services.qa_split_service import (
        QaSplitValidationError,
        validate_qa_split_output,
    )

    chunks = [
        DocumentChunk(chunk_index=0, content="退款需要主管审批。", page_no=1),
        DocumentChunk(chunk_index=1, content="已开票订单需先红冲发票。", page_no=2),
    ]
    payload = {"items": [{
        "question": "退款前要做什么？",
        "answer": "先红冲发票。",
        "quote": "不存在的引用。",
        "pageNo": 2,
    }]}

    with pytest.raises(QaSplitValidationError):
        validate_qa_split_output(
            json.dumps(payload), chunks, allow_legacy_missing_chunk_index=True
        )


def test_multi_batch_validation_retains_global_chunk_indexes(monkeypatch):
    import types

    from server.app.models.document import Document
    from server.app.models.qa_pair import DocumentChunk
    from server.app.services import qa_split_service
    from server.app.services.qa_split_service import QaSplitService

    monkeypatch.setattr(
        qa_split_service,
        "settings",
        types.SimpleNamespace(qa_split_max_batch_chars=12, qa_split_max_concurrency=1),
    )
    session, _identity = build_qa_session()
    chunks = [
        DocumentChunk(chunk_index=10, content="a" * 8, page_no=1),
        DocumentChunk(chunk_index=25, content="b" * 8, page_no=2),
    ]

    class Adapter:
        def __init__(self):
            self.calls = 0

        def generate_qa_pairs(self, _prompt):
            index = (10, 25)[self.calls]
            page = (1, 2)[self.calls]
            content = ("a" * 8, "b" * 8)[self.calls]
            self.calls += 1
            return json.dumps(_strict_qa_payload(
                items=[{
                    "question": f"q{index}",
                    "answer": "answer",
                    "quote": content,
                    "pageNo": page,
                    "chunkIndex": index,
                }],
                covered=[index],
                skipped=[],
            ))

    items = QaSplitService(session)._generate_qa_items(
        Adapter(), Document(title="T"), [[chunks[0]], [chunks[1]]]
    )

    assert [item.chunk_index for item in items] == [10, 25]



def _assert_provenance_error(exc_info, code, retryable):
    assert exc_info.value.code == code
    assert exc_info.value.retryable is retryable


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        pytest.param(field, value, id=f"{field}-{value_type}")
        for field in ("question", "answer", "quote")
        for value_type, value in (
            ("number", 123),
            ("bool", True),
            ("list", ["not-a-json-string"]),
            ("object", {"value": "not-a-json-string"}),
        )
    ],
)
def test_strict_qa_fields_reject_non_json_string_values(field, invalid_value):
    from server.app.services.qa_split_service import (
        QaSplitValidationError,
        validate_qa_split_output,
    )

    item = {
        "question": "question",
        "answer": "answer",
        # A numeric quote would match this content if coercion were allowed.
        "quote": "123",
        "pageNo": 1,
        "chunkIndex": 0,
    }
    item[field] = invalid_value
    payload = _strict_qa_payload(items=[item], covered=[0], skipped=[])
    chunks = [DocumentChunk(chunk_index=0, content="123", page_no=1)]

    with pytest.raises(QaSplitValidationError) as exc_info:
        validate_qa_split_output(json.dumps(payload), chunks)

    _assert_provenance_error(exc_info, "QA_PROVENANCE_CONTRACT_INVALID", False)


def test_numeric_quote_is_not_coerced_or_persisted_as_qa_pair():
    from server.app.models.document import Document
    from server.app.models.qa_pair import QaPair
    from server.app.services.qa_split_service import QaSplitService

    session, identity = build_qa_session()
    job_id, document_id, chunks = create_qa_ready_job(session, identity)
    chunks[0].content = "123"
    session.commit()
    add_default_qa_model(
        session,
        identity["tenant"].id,
        _strict_qa_payload(
            items=[{
                "question": "question",
                "answer": "answer",
                "quote": 123,
                "pageNo": 1,
                "chunkIndex": 0,
            }],
            covered=[0],
            skipped=[1],
        ),
    )

    result = QaSplitService(session).split_import_job(job_id)
    document = session.get(Document, document_id)

    assert result.status == "FAILED"
    assert document.last_error_code == "QA_PROVENANCE_CONTRACT_INVALID"
    assert session.scalars(
        select(QaPair).where(QaPair.document_id == document_id)
    ).all() == []


@pytest.mark.parametrize(
    ("page_start", "page_end"),
    [
        pytest.param(0, None, id="page-start-zero"),
        pytest.param(None, 0, id="page-end-zero"),
        pytest.param(False, None, id="page-start-false"),
        pytest.param(None, False, id="page-end-false"),
        pytest.param(2, 1, id="page-end-before-page-start"),
    ],
)
def test_chunk_page_range_rejects_invalid_values(page_start, page_end):
    from server.app.services.qa_split_service import (
        QaSplitValidationError,
        validate_qa_split_output,
    )

    payload = _strict_qa_payload(
        items=[{
            "question": "question",
            "answer": "answer",
            "quote": "content",
            "pageNo": 1,
            "chunkIndex": 0,
        }],
        covered=[0],
        skipped=[],
    )
    chunk = DocumentChunk(
        chunk_index=0,
        content="content",
        page_no=1,
        page_start=page_start,
        page_end=page_end,
    )

    with pytest.raises(QaSplitValidationError) as exc_info:
        validate_qa_split_output(json.dumps(payload), [chunk])

    _assert_provenance_error(exc_info, "QA_PROVENANCE_CONTRACT_INVALID", False)


@pytest.mark.parametrize(
    ("payload", "chunks", "code", "retryable"),
    [
        (
            _strict_qa_payload(
                items=[{
                    "question": "退款需要谁审批？",
                    "answer": "退款需要主管审批。",
                    "quote": "退款需要主管审批。",
                    "pageNo": 1,
                }],
                covered=[0],
                skipped=[],
            ),
            [DocumentChunk(chunk_index=0, content="退款需要主管审批。", page_no=1)],
            "QA_PROVENANCE_MISSING_CHUNK_INDEX",
            True,
        ),
        (
            _strict_qa_payload(
                items=[{
                    "question": "退款需要谁审批？",
                    "answer": "退款需要主管审批。",
                    "quote": "退款需要主管审批。",
                    "pageNo": 1,
                    "chunkIndex": 9,
                }],
                covered=[0],
                skipped=[],
            ),
            [DocumentChunk(chunk_index=0, content="退款需要主管审批。", page_no=1)],
            "QA_PROVENANCE_UNKNOWN_CHUNK_INDEX",
            True,
        ),
        (
            _strict_qa_payload(
                items=[{
                    "question": "退款需要谁审批？",
                    "answer": "退款需要主管审批。",
                    "quote": "不属于当前 Chunk。",
                    "pageNo": 1,
                    "chunkIndex": 0,
                }],
                covered=[0],
                skipped=[],
            ),
            [DocumentChunk(chunk_index=0, content="退款需要主管审批。", page_no=1)],
            "QA_PROVENANCE_QUOTE_MISMATCH",
            True,
        ),
        (
            _strict_qa_payload(
                items=[{
                    "question": "退款需要谁审批？",
                    "answer": "退款需要主管审批。",
                    "quote": "退款需要主管审批。",
                    "pageNo": 1,
                    "chunkIndex": 0,
                }],
                covered=[],
                skipped=[],
            ),
            [DocumentChunk(chunk_index=0, content="退款需要主管审批。", page_no=1)],
            "QA_PROVENANCE_COVERAGE_MISMATCH",
            True,
        ),
        (
            _strict_qa_payload(
                items=[],
                covered=[],
                skipped=[],
            ),
            [
                DocumentChunk(chunk_index=0, content="first", page_no=1),
                DocumentChunk(chunk_index=0, content="second", page_no=2),
            ],
            "QA_PROVENANCE_CONTRACT_INVALID",
            False,
        ),
    ],
)
def test_provenance_failures_have_spec_codes_and_retryability(
    payload, chunks, code, retryable
):
    from server.app.services.qa_split_service import (
        QaSplitValidationError,
        validate_qa_split_output,
    )

    with pytest.raises(QaSplitValidationError) as exc_info:
        validate_qa_split_output(json.dumps(payload), chunks)

    _assert_provenance_error(exc_info, code, retryable)


def test_legacy_missing_chunk_index_requires_constructor_compatibility_flag():
    from server.app.models.document import Document
    from server.app.models.qa_pair import DocumentChunk
    from server.app.services.qa_split_service import QaSplitService, QaSplitValidationError

    session, _identity = build_qa_session()
    chunks = [
        DocumentChunk(chunk_index=0, content="first fact", page_no=1),
        DocumentChunk(chunk_index=1, content="second fact", page_no=2),
    ]
    output = json.dumps({"items": [
        {
            "question": "first?",
            "answer": "first",
            "quote": "first fact",
            "pageNo": 1,
        },
        {
            "question": "second?",
            "answer": "second",
            "quote": "second fact",
            "pageNo": 2,
        },
    ]})

    class Adapter:
        def generate_qa_pairs(self, _prompt):
            return output

    with pytest.raises(QaSplitValidationError) as exc_info:
        QaSplitService(session)._generate_qa_items(Adapter(), Document(title="T"), [chunks])
    _assert_provenance_error(exc_info, "QA_PROVENANCE_MISSING_CHUNK_INDEX", True)

    accepted = QaSplitService(
        session, legacy_missing_chunk_index_compatibility=True
    )._generate_qa_items(Adapter(), Document(title="T"), [chunks])
    assert [item.chunk_index for item in accepted] == [0, 1]


def test_compatibility_log_never_contains_quote_or_content(monkeypatch):
    from server.app.models.document import Document
    from server.app.models.qa_pair import DocumentChunk
    from server.app.services import qa_split_service
    from server.app.services.qa_split_service import QaSplitService

    secret_quote = "UNIQUE-QUOTE-DO-NOT-LOG"
    secret_content = f"prefix {secret_quote} suffix"
    session, _identity = build_qa_session()
    chunks = [DocumentChunk(chunk_index=0, content=secret_content, page_no=1)]
    log_calls = []

    def capture_info(message, *args, **kwargs):
        log_calls.append((message, args, kwargs))

    monkeypatch.setattr(qa_split_service.logger, "info", capture_info)

    class Adapter:
        def generate_qa_pairs(self, _prompt):
            return json.dumps({"items": [{
                "question": "q",
                "answer": "a",
                "quote": secret_quote,
                "pageNo": 1,
            }]})

    QaSplitService(
        session, legacy_missing_chunk_index_compatibility=True
    )._generate_qa_items(Adapter(), Document(title="T"), [chunks])

    assert log_calls == [
        ("qa_provenance_legacy_compatibility_total", (), {"extra": {"result": "accepted"}})
    ]
    assert secret_quote not in repr(log_calls)
    assert secret_content not in repr(log_calls)


def test_invalid_json_does_not_persist_raw_model_output_in_failure_messages():
    secret_output = "SECRET-MODEL-OUTPUT-MUST-NOT-PERSIST"
    session, identity = build_qa_session()
    tenant_id = identity["tenant"].id
    job_id, document_id, _chunks = create_qa_ready_job(session, identity)
    add_default_qa_model(session, tenant_id, f"not-json: {secret_output}")

    from server.app.models.document import Document
    from server.app.models.import_job import ImportJob
    from server.app.models.logs import TaskRun
    from server.app.services.qa_split_service import (
        QaSplitService,
        QaSplitValidationError,
        validate_qa_split_output,
    )

    with pytest.raises(QaSplitValidationError) as exc_info:
        validate_qa_split_output(f"not-json: {secret_output}")
    assert secret_output not in exc_info.value.message

    QaSplitService(session).split_import_job(job_id)
    document = session.get(Document, document_id)
    job = session.get(ImportJob, job_id)
    task_run = session.scalar(select(TaskRun).where(TaskRun.resource_id == job_id))

    assert secret_output not in (document.last_error_message or "")
    assert secret_output not in (job.error_message or "")
    assert secret_output not in json.dumps(task_run.error, ensure_ascii=False)


def test_unexpected_qa_provider_error_does_not_leak_raw_exception_to_logs(caplog):
    from server.app.services import qa_split_service
    from server.app.services.qa_split_service import QaSplitService

    secret = "PROVIDER_RAW_SECRET_DO-NOT-LOG"
    session, identity = build_qa_session()
    job_id, _document_id, _chunks = create_qa_ready_job(session, identity)
    add_default_qa_model(session, identity["tenant"].id, {"items": []})

    class _Adapter:
        @staticmethod
        def generate_qa_pairs(_prompt):
            raise RuntimeError(secret)

    caplog.set_level("ERROR", logger=qa_split_service.__name__)
    result = QaSplitService(
        session,
        provider_factory=lambda *_args, **_kwargs: _Adapter(),
    ).split_import_job(job_id)

    assert result.status == "FAILED"
    assert secret not in caplog.text


def test_later_invalid_batch_leaves_no_qa_pairs_from_earlier_valid_batch(monkeypatch):
    import types

    from server.app.models.document import Document
    from server.app.models.import_job import ImportJob
    from server.app.models.qa_pair import QaPair
    from server.app.services import qa_split_service
    from server.app.services.qa_split_service import QaSplitService

    monkeypatch.setattr(
        qa_split_service,
        "settings",
        types.SimpleNamespace(qa_split_max_batch_chars=12, qa_split_max_concurrency=1),
    )
    session, identity = build_qa_session()
    job_id, document_id, chunks = create_qa_ready_job(session, identity)
    for chunk in chunks:
        chunk.chunker_name = "adaptive_hierarchical"
        chunk.chunker_config_hash = "adaptive-generation"
    session.commit()
    add_default_qa_model(session, identity["tenant"].id, {"items": []})

    class Adapter:
        calls = 0

        def generate_qa_pairs(self, _prompt):
            type(self).calls += 1
            if type(self).calls == 1:
                return json.dumps(_strict_qa_payload(
                    items=[{
                        "question": "退款需要谁审批？",
                        "answer": "退款需要主管审批。",
                        "quote": "退款需要主管审批。",
                        "pageNo": 1,
                        "chunkIndex": 0,
                    }],
                    covered=[0],
                    skipped=[],
                ))
            return json.dumps(_strict_qa_payload(
                items=[{
                    "question": "已开票订单退款前要做什么？",
                    "answer": "先红冲发票。",
                    "quote": "已开票订单需先红冲发票。",
                    "pageNo": 2,
                    "chunkIndex": 999,
                }],
                covered=[1],
                skipped=[],
            ))

    service = QaSplitService(session, provider_factory=lambda *_args, **_kwargs: Adapter())
    result = service.split_import_job(job_id)

    document = session.get(Document, document_id)
    job = session.get(ImportJob, job_id)

    assert result.status == "FAILED"
    assert Adapter.calls == 2
    assert document.last_error_code == "QA_PROVENANCE_UNKNOWN_CHUNK_INDEX"
    assert job.error_code == "QA_PROVENANCE_UNKNOWN_CHUNK_INDEX"
    assert session.scalars(select(QaPair).where(QaPair.document_id == document_id)).all() == []
