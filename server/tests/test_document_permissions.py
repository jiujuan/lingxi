from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def build_session():
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


def test_authorized_qa_query_filters_by_department_role_user_and_soft_delete():
    from server.app.core.permissions import AccessContext
    from server.app.models.document import (
        Document,
        DocumentAccessRule,
        DocumentAccessSubjectType,
        DocumentStatus,
    )
    from server.app.models.qa_pair import QaPair
    from server.app.repositories.document_repo import DocumentRepository

    session, identity = build_session()

    tenant_id = identity["tenant"].id
    employee = identity["users"]["employee"]
    employee_role = identity["roles"]["employee"]
    support_department = identity["departments"]["support"]
    private_department = identity["departments"]["private"]

    department_doc = Document(
        tenant_id=tenant_id,
        title="Support SOP",
        file_name="support.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=100,
        object_key="documents/support.pdf",
        checksum="support",
        status=DocumentStatus.READY,
    )
    private_doc = Document(
        tenant_id=tenant_id,
        title="Private SOP",
        file_name="private.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=100,
        object_key="documents/private.pdf",
        checksum="private",
        status=DocumentStatus.READY,
    )
    role_doc = Document(
        tenant_id=tenant_id,
        title="Employee Handbook",
        file_name="handbook.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=100,
        object_key="documents/handbook.pdf",
        checksum="handbook",
        status=DocumentStatus.READY,
    )
    user_doc = Document(
        tenant_id=tenant_id,
        title="Direct Grant",
        file_name="direct.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=100,
        object_key="documents/direct.pdf",
        checksum="direct",
        status=DocumentStatus.READY,
    )
    deleted_doc = Document(
        tenant_id=tenant_id,
        title="Deleted",
        file_name="deleted.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=100,
        object_key="documents/deleted.pdf",
        checksum="deleted",
        status=DocumentStatus.DELETED,
    )
    session.add_all([department_doc, private_doc, role_doc, user_doc, deleted_doc])
    session.flush()

    session.add_all(
        [
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=department_doc.id,
                subject_type=DocumentAccessSubjectType.DEPARTMENT,
                subject_id=support_department.id,
            ),
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=private_doc.id,
                subject_type=DocumentAccessSubjectType.DEPARTMENT,
                subject_id=private_department.id,
            ),
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=role_doc.id,
                subject_type=DocumentAccessSubjectType.ROLE,
                subject_id=employee_role.id,
            ),
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=user_doc.id,
                subject_type=DocumentAccessSubjectType.USER,
                subject_id=employee.id,
            ),
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=deleted_doc.id,
                subject_type=DocumentAccessSubjectType.ALL_AUTHENTICATED,
                subject_id=None,
            ),
        ]
    )

    for index, document in enumerate(
        [department_doc, private_doc, role_doc, user_doc, deleted_doc]
    ):
        session.add(
            QaPair(
                tenant_id=tenant_id,
                document_id=document.id,
                pair_index=index,
                question=f"question-{document.title}",
                answer="answer",
                search_text=document.title,
                status="ACTIVE",
            )
        )
    session.commit()

    context = AccessContext(
        tenant_id=tenant_id,
        user_id=employee.id,
        department_id=support_department.id,
        role_ids=[employee_role.id],
        permissions={"DOCUMENT_READ"},
    )

    results = DocumentRepository(session).list_authorized_qa_pairs(context)
    questions = {item.question for item in results}

    assert questions == {
        "question-Support SOP",
        "question-Employee Handbook",
        "question-Direct Grant",
    }


def test_document_list_classification_filters_keep_access_department_semantics():
    from server.app.core.permissions import AccessContext
    from server.app.models.document import (
        Document,
        DocumentAccessRule,
        DocumentAccessSubjectType,
        DocumentStatus,
    )
    from server.app.models.knowledge_category import KnowledgeCategory, KnowledgeSpace
    from server.app.repositories.document_repo import DocumentRepository

    session, identity = build_session()

    tenant_id = identity["tenant"].id
    employee = identity["users"]["employee"]
    employee_role = identity["roles"]["employee"]
    support_department = identity["departments"]["support"]
    private_department = identity["departments"]["private"]

    support_space = KnowledgeSpace(
        tenant_id=tenant_id,
        name="Support Space",
        code="support-space",
    )
    private_space = KnowledgeSpace(
        tenant_id=tenant_id,
        name="Private Space",
        code="private-space",
    )
    session.add_all([support_space, private_space])
    session.flush()

    support_category = KnowledgeCategory(
        tenant_id=tenant_id,
        space_id=support_space.id,
        department_id=support_department.id,
        name="Support Topic",
        code="support-topic",
    )
    private_category = KnowledgeCategory(
        tenant_id=tenant_id,
        space_id=private_space.id,
        department_id=private_department.id,
        name="Private Topic",
        code="private-topic",
    )
    session.add_all([support_category, private_category])
    session.flush()

    support_doc = Document(
        tenant_id=tenant_id,
        title="Support Classified",
        file_name="support.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=100,
        object_key="documents/support.pdf",
        checksum="support",
        status=DocumentStatus.READY,
        knowledge_space_id=support_space.id,
        category_department_id=support_department.id,
        knowledge_category_id=support_category.id,
    )
    private_classified_but_support_granted = Document(
        tenant_id=tenant_id,
        title="Private Classified Support Grant",
        file_name="mixed.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=100,
        object_key="documents/mixed.pdf",
        checksum="mixed",
        status=DocumentStatus.READY,
        knowledge_space_id=private_space.id,
        category_department_id=private_department.id,
        knowledge_category_id=private_category.id,
    )
    private_doc = Document(
        tenant_id=tenant_id,
        title="Private Classified Private Grant",
        file_name="private.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=100,
        object_key="documents/private.pdf",
        checksum="private",
        status=DocumentStatus.READY,
        knowledge_space_id=private_space.id,
        category_department_id=private_department.id,
        knowledge_category_id=private_category.id,
    )
    session.add_all(
        [support_doc, private_classified_but_support_granted, private_doc]
    )
    session.flush()

    session.add_all(
        [
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=support_doc.id,
                subject_type=DocumentAccessSubjectType.DEPARTMENT,
                subject_id=support_department.id,
            ),
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=private_classified_but_support_granted.id,
                subject_type=DocumentAccessSubjectType.DEPARTMENT,
                subject_id=support_department.id,
            ),
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=private_doc.id,
                subject_type=DocumentAccessSubjectType.DEPARTMENT,
                subject_id=private_department.id,
            ),
        ]
    )
    session.commit()

    context = AccessContext(
        tenant_id=tenant_id,
        user_id=employee.id,
        department_id=support_department.id,
        role_ids=[employee_role.id],
        permissions={"DOCUMENT_READ"},
    )
    repository = DocumentRepository(session)

    support_space_results, _ = repository.list_documents(
        context, space_id=support_space.id
    )
    assert {item.title for item in support_space_results} == {"Support Classified"}

    private_department_results, _ = repository.list_documents(
        context, classification_department_id=private_department.id
    )
    assert {item.title for item in private_department_results} == {
        "Private Classified Support Grant"
    }

    private_category_results, _ = repository.list_documents(
        context, category_id=private_category.id
    )
    assert {item.title for item in private_category_results} == {
        "Private Classified Support Grant"
    }

    authorized_department_results, _ = repository.list_documents(
        context, department_id=support_department.id
    )
    assert {item.title for item in authorized_department_results} == {
        "Support Classified",
        "Private Classified Support Grant",
    }

    mixed_results, _ = repository.list_documents(
        context,
        department_id=support_department.id,
        classification_department_id=private_department.id,
    )
    assert {item.title for item in mixed_results} == {
        "Private Classified Support Grant"
    }


def test_document_list_unclassified_filter_keeps_authorization_boundary():
    from server.app.core.permissions import AccessContext
    from server.app.models.document import (
        Document,
        DocumentAccessRule,
        DocumentAccessSubjectType,
        DocumentStatus,
    )
    from server.app.models.knowledge_category import KnowledgeCategory, KnowledgeSpace
    from server.app.repositories.document_repo import DocumentRepository

    session, identity = build_session()
    tenant_id = identity["tenant"].id
    employee = identity["users"]["employee"]
    employee_role = identity["roles"]["employee"]
    support_department = identity["departments"]["support"]
    private_department = identity["departments"]["private"]

    support_space = KnowledgeSpace(
        tenant_id=tenant_id,
        name="Support Space",
        code="support-space-unclassified",
    )
    session.add(support_space)
    session.flush()
    support_category = KnowledgeCategory(
        tenant_id=tenant_id,
        space_id=support_space.id,
        department_id=support_department.id,
        name="Support Topic",
        code="support-topic-unclassified",
    )
    session.add(support_category)
    session.flush()

    authorized_unclassified = Document(
        tenant_id=tenant_id,
        title="Authorized Unclassified",
        file_name="authorized.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=100,
        object_key="documents/authorized.pdf",
        checksum="authorized-unclassified",
        status=DocumentStatus.READY,
    )
    unauthorized_unclassified = Document(
        tenant_id=tenant_id,
        title="Unauthorized Unclassified",
        file_name="unauthorized.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=100,
        object_key="documents/unauthorized.pdf",
        checksum="unauthorized-unclassified",
        status=DocumentStatus.READY,
    )
    classified = Document(
        tenant_id=tenant_id,
        title="Authorized Classified",
        file_name="classified.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=100,
        object_key="documents/classified.pdf",
        checksum="classified",
        status=DocumentStatus.READY,
        knowledge_space_id=support_space.id,
        category_department_id=support_department.id,
        knowledge_category_id=support_category.id,
    )
    session.add_all([authorized_unclassified, unauthorized_unclassified, classified])
    session.flush()
    session.add_all(
        [
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=authorized_unclassified.id,
                subject_type=DocumentAccessSubjectType.DEPARTMENT,
                subject_id=support_department.id,
            ),
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=unauthorized_unclassified.id,
                subject_type=DocumentAccessSubjectType.DEPARTMENT,
                subject_id=private_department.id,
            ),
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=classified.id,
                subject_type=DocumentAccessSubjectType.DEPARTMENT,
                subject_id=support_department.id,
            ),
        ]
    )
    session.commit()

    context = AccessContext(
        tenant_id=tenant_id,
        user_id=employee.id,
        department_id=support_department.id,
        role_ids=[employee_role.id],
        permissions={"DOCUMENT_READ"},
    )

    results, total = DocumentRepository(session).list_documents(
        context, is_unclassified=True
    )

    assert total == 1
    assert [item.title for item in results] == ["Authorized Unclassified"]


def test_bulk_classification_rejects_inaccessible_document_without_partial_update():
    from types import SimpleNamespace

    from fastapi import HTTPException

    from server.app.core.permissions import AccessContext
    from server.app.models.document import (
        Document,
        DocumentAccessRule,
        DocumentAccessSubjectType,
        DocumentStatus,
    )
    from server.app.models.knowledge_category import KnowledgeCategory, KnowledgeSpace
    from server.app.services.document_center_service import DocumentCenterService

    session, identity = build_session()
    tenant_id = identity["tenant"].id
    employee = identity["users"]["employee"]
    employee_role = identity["roles"]["employee"]
    support_department = identity["departments"]["support"]
    private_department = identity["departments"]["private"]

    space = KnowledgeSpace(tenant_id=tenant_id, name="Bulk Space", code="bulk-space")
    session.add(space)
    session.flush()
    category = KnowledgeCategory(
        tenant_id=tenant_id,
        space_id=space.id,
        department_id=support_department.id,
        name="Bulk Topic",
        code="bulk-topic",
    )
    session.add(category)
    session.flush()

    authorized = Document(
        tenant_id=tenant_id,
        title="Authorized Bulk",
        file_name="authorized.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=100,
        object_key="documents/authorized-bulk.pdf",
        checksum="authorized-bulk",
        status=DocumentStatus.READY,
        knowledge_space_id=space.id,
        category_department_id=support_department.id,
        knowledge_category_id=category.id,
    )
    inaccessible = Document(
        tenant_id=tenant_id,
        title="Inaccessible Bulk",
        file_name="inaccessible.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=100,
        object_key="documents/inaccessible-bulk.pdf",
        checksum="inaccessible-bulk",
        status=DocumentStatus.READY,
        knowledge_space_id=space.id,
        category_department_id=support_department.id,
        knowledge_category_id=category.id,
    )
    session.add_all([authorized, inaccessible])
    session.flush()
    session.add_all(
        [
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=authorized.id,
                subject_type=DocumentAccessSubjectType.DEPARTMENT,
                subject_id=support_department.id,
            ),
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=inaccessible.id,
                subject_type=DocumentAccessSubjectType.DEPARTMENT,
                subject_id=private_department.id,
            ),
        ]
    )
    session.commit()

    context = AccessContext(
        tenant_id=tenant_id,
        user_id=employee.id,
        department_id=support_department.id,
        role_ids=[employee_role.id],
        role_codes={"EMPLOYEE"},
        permissions={"DOCUMENT_READ", "DOCUMENT_WRITE"},
    )
    payload = SimpleNamespace(
        document_ids=[authorized.id, inaccessible.id],
        classification=None,
    )

    try:
        DocumentCenterService(session).bulk_update_classification(context, payload)
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("批量归类应拒绝不可访问文档")

    session.refresh(authorized)
    session.refresh(inaccessible)
    assert authorized.knowledge_category_id == category.id
    assert inaccessible.knowledge_category_id == category.id


def test_retrieval_qa_and_chunk_share_tenant_acl_and_classification_scope():
    from server.app.core.permissions import AccessContext
    from server.app.models.document import (
        Document,
        DocumentAccessRule,
        DocumentAccessSubjectType,
        DocumentStatus,
    )
    from server.app.models.qa_pair import DocumentChunk, QaPair
    from server.app.repositories.retrieval_repo import RetrievalRepository
    from server.app.schemas.retrieval import RetrievalAccessScope

    session, identity = build_session()
    tenant_id = identity["tenant"].id
    context = AccessContext(
        tenant_id=tenant_id,
        user_id=identity["users"]["employee"].id,
        department_id=identity["departments"]["support"].id,
        role_ids=[identity["roles"]["employee"].id],
        permissions={"DOCUMENT_READ"},
    )
    allowed = Document(
        tenant_id=tenant_id,
        title="Allowed",
        file_name="allowed.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=1,
        object_key="documents/allowed.pdf",
        checksum="allowed",
        status=DocumentStatus.READY,
        knowledge_space_id="space-1",
        category_department_id="dept-1",
        knowledge_category_id="cat-1",
    )
    denied = Document(
        tenant_id=tenant_id,
        title="Denied",
        file_name="denied.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=1,
        object_key="documents/denied.pdf",
        checksum="denied",
        status=DocumentStatus.READY,
        knowledge_space_id="space-1",
        category_department_id="dept-1",
        knowledge_category_id="cat-1",
    )
    session.add_all([allowed, denied])
    session.flush()
    session.add(
        DocumentAccessRule(
            tenant_id=tenant_id,
            document_id=allowed.id,
            subject_type=DocumentAccessSubjectType.DEPARTMENT,
            subject_id=context.department_id,
        )
    )
    allowed_parent = DocumentChunk(
        tenant_id=tenant_id,
        document_id=allowed.id,
        chunk_index=0,
        content="allowed parent",
        chunk_level="PARENT",
        status="ACTIVE",
    )
    denied_parent = DocumentChunk(
        tenant_id=tenant_id,
        document_id=denied.id,
        chunk_index=0,
        content="denied parent",
        chunk_level="PARENT",
        status="ACTIVE",
    )
    allowed_child = DocumentChunk(
        tenant_id=tenant_id,
        document_id=allowed.id,
        chunk_index=1,
        content="allowed chunk",
        search_text="allowed chunk",
        chunk_level="CHILD",
        parent_chunk=allowed_parent,
        status="ACTIVE",
        embedding=[1.0, 0.0],
    )
    denied_child = DocumentChunk(
        tenant_id=tenant_id,
        document_id=denied.id,
        chunk_index=1,
        content="denied chunk",
        search_text="denied chunk",
        chunk_level="CHILD",
        parent_chunk=denied_parent,
        status="ACTIVE",
        embedding=[1.0, 0.0],
    )
    session.add_all(
        [
            allowed_parent,
            denied_parent,
            allowed_child,
            denied_child,
            QaPair(
                tenant_id=tenant_id,
                document_id=allowed.id,
                chunk_id=allowed_child.id,
                pair_index=0,
                question="allowed qa",
                answer="answer",
                search_text="allowed qa",
                question_embedding=[1.0, 0.0],
                status="ACTIVE",
            ),
            QaPair(
                tenant_id=tenant_id,
                document_id=denied.id,
                chunk_id=denied_child.id,
                pair_index=0,
                question="denied qa",
                answer="answer",
                search_text="denied qa",
                question_embedding=[1.0, 0.0],
                status="ACTIVE",
            ),
        ]
    )
    session.commit()
    scope = RetrievalAccessScope(
        space_id="space-1",
        classification_department_id="dept-1",
        category_id="cat-1",
    )
    repo = RetrievalRepository(session)

    qa_ids = [
        pair.document_id
        for pair, _score in repo.search_qa_vector(context, [1.0, 0.0], 10, scope)
    ]
    chunk_ids = [
        chunk.document_id
        for chunk, _score in repo.search_chunk_vector(context, [1.0, 0.0], 10, scope)
    ]

    assert qa_ids == [allowed.id]
    assert chunk_ids == [allowed.id]
