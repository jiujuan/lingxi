from sqlalchemy import select

from server.tests.test_document_permissions import build_session


def _seed_retrieval_dataset(session, identity):
    from server.app.models.document import (
        Document,
        DocumentAccessRule,
        DocumentAccessSubjectType,
        DocumentStatus,
    )
    from server.app.models.qa_pair import QaPair

    tenant_id = identity["tenant"].id
    support = identity["departments"]["support"]
    private = identity["departments"]["private"]

    refund_doc = Document(
        tenant_id=tenant_id,
        title="Refund SOP",
        file_name="refund.md",
        file_type="MARKDOWN",
        mime_type="text/markdown",
        file_size=100,
        object_key="documents/refund.md",
        checksum="refund",
        status=DocumentStatus.READY,
        knowledge_space_id="space-support",
        category_department_id=support.id,
        knowledge_category_id="cat-refund",
    )
    invoice_doc = Document(
        tenant_id=tenant_id,
        title="Invoice SOP",
        file_name="invoice.md",
        file_type="MARKDOWN",
        mime_type="text/markdown",
        file_size=100,
        object_key="documents/invoice.md",
        checksum="invoice",
        status=DocumentStatus.READY,
        knowledge_space_id="space-support",
        category_department_id=support.id,
        knowledge_category_id="cat-invoice",
    )
    private_doc = Document(
        tenant_id=tenant_id,
        title="Private Payroll",
        file_name="payroll.md",
        file_type="MARKDOWN",
        mime_type="text/markdown",
        file_size=100,
        object_key="documents/payroll.md",
        checksum="payroll",
        status=DocumentStatus.READY,
        knowledge_space_id="space-support",
        category_department_id=support.id,
        knowledge_category_id="cat-refund",
    )
    session.add_all([refund_doc, invoice_doc, private_doc])
    session.flush()

    pairs = [
        QaPair(
            tenant_id=tenant_id,
            document_id=refund_doc.id,
            pair_index=0,
            question="退款需要谁审批？",
            answer="退款需要主管审批。",
            quote="退款需要主管审批。",
            page_no=1,
            question_embedding=[1.0, 0.0, 0.0, 0.0],
            search_text="退款 需要 主管 审批",
            status="ACTIVE",
        ),
        QaPair(
            tenant_id=tenant_id,
            document_id=invoice_doc.id,
            pair_index=1,
            question="已开票订单退款前要做什么？",
            answer="已开票订单退款前需要先红冲发票。",
            quote="已开票订单需先红冲发票。",
            page_no=2,
            question_embedding=[0.8, 0.2, 0.0, 0.0],
            search_text="已 开票 订单 退款 前 红冲 发票",
            status="ACTIVE",
        ),
        QaPair(
            tenant_id=tenant_id,
            document_id=private_doc.id,
            pair_index=0,
            question="工资表在哪里？",
            answer="工资表在财务私有目录。",
            quote="工资表在财务私有目录。",
            page_no=1,
            question_embedding=[1.0, 0.0, 0.0, 0.0],
            search_text="工资 表 财务 私有",
            status="ACTIVE",
        ),
    ]
    session.add_all(pairs)
    session.add_all(
        [
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=refund_doc.id,
                subject_type=DocumentAccessSubjectType.ALL_AUTHENTICATED,
                subject_id=None,
            ),
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=invoice_doc.id,
                subject_type=DocumentAccessSubjectType.DEPARTMENT,
                subject_id=support.id,
            ),
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=private_doc.id,
                subject_type=DocumentAccessSubjectType.DEPARTMENT,
                subject_id=private.id,
            ),
        ]
    )
    session.commit()
    return {"refund_doc": refund_doc.id, "invoice_doc": invoice_doc.id, "private_doc": private_doc.id}


def _employee_context(identity):
    from server.app.core.permissions import AccessContext

    return AccessContext(
        tenant_id=identity["tenant"].id,
        user_id=identity["users"]["employee"].id,
        department_id=identity["departments"]["support"].id,
        role_ids=[identity["roles"]["employee"].id],
        permissions={"DOCUMENT_READ", "CHAT_READ", "CHAT_WRITE"},
        role_codes={"EMPLOYEE"},
    )


def test_retrieval_fuses_vector_and_text_reranks_and_keeps_snapshot():
    session, identity = build_session()
    _seed_retrieval_dataset(session, identity)

    from server.app.services.retrieval_service import RetrievalService

    result = RetrievalService(session).retrieve(
        _employee_context(identity), "已开票订单退款前要做什么？"
    )

    assert result.has_answer is True
    assert result.candidates[0].question == "已开票订单退款前要做什么？"
    assert result.snapshot["stages"]["vector"]
    assert result.snapshot["stages"]["text"]
    assert result.snapshot["stages"]["rrf"]
    assert result.snapshot["stages"]["rerank"]
    assert result.snapshot["latencyMs"] >= 0


def test_retrieval_filters_unauthorized_and_api_key_scope_before_scoring():
    session, identity = build_session()
    ids = _seed_retrieval_dataset(session, identity)

    from server.app.schemas.retrieval import RetrievalAccessScope
    from server.app.services.retrieval_service import RetrievalService

    result = RetrievalService(session).retrieve(_employee_context(identity), "工资表在哪里？")

    assert {item.document_id for item in result.candidates} <= {
        ids["refund_doc"],
        ids["invoice_doc"],
    }

    scoped = RetrievalService(session).retrieve(
        _employee_context(identity),
        "已开票订单退款前要做什么？",
        access_scope=RetrievalAccessScope(document_ids={ids["refund_doc"]}),
    )

    assert scoped.candidates
    assert {item.document_id for item in scoped.candidates} == {ids["refund_doc"]}


def test_retrieval_classification_scope_filters_without_expanding_access():
    session, identity = build_session()
    ids = _seed_retrieval_dataset(session, identity)

    from server.app.schemas.retrieval import RetrievalAccessScope
    from server.app.services.retrieval_service import RetrievalService

    result = RetrievalService(session).retrieve(
        _employee_context(identity),
        "退款需要谁审批？",
        access_scope=RetrievalAccessScope(
            space_id="space-support",
            classification_department_id=identity["departments"]["support"].id,
            category_id="cat-refund",
        ),
    )

    assert result.candidates
    assert {item.document_id for item in result.candidates} == {ids["refund_doc"]}
    assert result.snapshot["filters"]["scopeSpaceId"] == "space-support"
    assert (
        result.snapshot["filters"]["scopeClassificationDepartmentId"]
        == identity["departments"]["support"].id
    )
    assert result.snapshot["filters"]["scopeCategoryId"] == "cat-refund"


def test_retrieval_classification_scope_supports_space_only():
    session, identity = build_session()
    ids = _seed_retrieval_dataset(session, identity)

    from server.app.schemas.retrieval import RetrievalAccessScope
    from server.app.services.retrieval_service import RetrievalService

    result = RetrievalService(session).retrieve(
        _employee_context(identity),
        "已开票订单退款前要做什么？",
        access_scope=RetrievalAccessScope(space_id="space-support"),
    )

    assert {item.document_id for item in result.candidates} <= {
        ids["refund_doc"],
        ids["invoice_doc"],
    }
    assert ids["private_doc"] not in {item.document_id for item in result.candidates}


def test_normalize_retrieval_scope_rejects_partial_classification_paths():
    import pytest

    from server.app.schemas.retrieval import RetrievalAccessScope
    from server.app.services.retrieval_service import normalize_retrieval_scope

    with pytest.raises(
        ValueError, match="classification_department_id requires space_id"
    ):
        normalize_retrieval_scope(
            RetrievalAccessScope(classification_department_id="dept-1")
        )

    with pytest.raises(
        ValueError,
        match="category_id requires space_id and classification_department_id",
    ):
        normalize_retrieval_scope(
            RetrievalAccessScope(space_id="space-1", category_id="cat-1")
        )


def test_snapshot_stages_are_capped_per_config():
    from dataclasses import replace

    session, identity = build_session()
    _seed_retrieval_dataset(session, identity)

    from server.app.core.retrieval_config import get_retrieval_config
    from server.app.services.retrieval_service import RetrievalService

    capped_config = replace(get_retrieval_config(), snapshot_max_items_per_stage=1)
    result = RetrievalService(session, config=capped_config).retrieve(
        _employee_context(identity), "已开票订单退款前要做什么？"
    )

    for stage in ("vector", "text", "rrf", "rerank"):
        assert len(result.snapshot["stages"][stage]) <= 1


def test_low_confidence_records_missed_question():
    session, identity = build_session()
    _seed_retrieval_dataset(session, identity)

    from server.app.models.chat import MissedQuestion
    from server.app.services.retrieval_service import RetrievalService

    result = RetrievalService(session).retrieve(
        _employee_context(identity), "火星基地报销制度是什么？"
    )

    missed = session.scalars(select(MissedQuestion)).all()
    assert result.has_answer is False
    assert missed
    assert missed[0].missed_metadata["requestId"].startswith("req_")
