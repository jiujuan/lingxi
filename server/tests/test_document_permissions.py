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
