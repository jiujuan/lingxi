import importlib

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _build_session():
    from server.app.db.base import Base

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return engine, SessionLocal()


def test_create_all_registers_knowledge_models_and_document_classification_fields():
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.knowledge_category import (
        KnowledgeCategory,
        KnowledgeCategoryType,
        KnowledgeSpace,
    )
    from server.app.models.user import Department, Tenant

    engine, session = _build_session()
    inspector = inspect(engine)

    assert "knowledge_spaces" in inspector.get_table_names()
    assert "knowledge_categories" in inspector.get_table_names()

    document_columns = {column["name"] for column in inspector.get_columns("documents")}
    assert {
        "knowledge_space_id",
        "category_department_id",
        "knowledge_category_id",
    }.issubset(document_columns)

    tenant = Tenant(name="默认租户")
    session.add(tenant)
    session.flush()

    department = Department(tenant_id=tenant.id, name="客服部", code="support")
    space = KnowledgeSpace(
        tenant_id=tenant.id,
        name="客服知识库",
        code="support-kb",
        description="客服团队使用的知识库空间",
    )
    session.add_all([department, space])
    session.flush()

    category = KnowledgeCategory(
        tenant_id=tenant.id,
        space_id=space.id,
        department_id=department.id,
        name="退款专题",
        code="refund-topic",
        category_type=KnowledgeCategoryType.TOPIC,
    )
    session.add(category)
    session.flush()

    unclassified_document = Document(
        tenant_id=tenant.id,
        title="未分类文档",
        file_name="uncategorized.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=100,
        object_key="documents/uncategorized.pdf",
        checksum="uncategorized",
        status=DocumentStatus.UPLOADED,
    )
    classified_document = Document(
        tenant_id=tenant.id,
        title="退款流程",
        file_name="refund.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=200,
        object_key="documents/refund.pdf",
        checksum="refund",
        status=DocumentStatus.READY,
        knowledge_space_id=space.id,
        category_department_id=department.id,
        knowledge_category_id=category.id,
    )
    session.add_all([category, unclassified_document, classified_document])
    session.commit()

    stored_space = session.scalar(
        select(KnowledgeSpace).where(KnowledgeSpace.code == "support-kb")
    )
    assert stored_space is not None
    assert stored_space.name == "客服知识库"

    stored_category = session.scalar(
        select(KnowledgeCategory).where(KnowledgeCategory.code == "refund-topic")
    )
    assert stored_category is not None
    assert stored_category.category_type == KnowledgeCategoryType.TOPIC

    stored_unclassified = session.get(Document, unclassified_document.id)
    assert stored_unclassified is not None
    assert stored_unclassified.knowledge_space_id is None
    assert stored_unclassified.category_department_id is None
    assert stored_unclassified.knowledge_category_id is None

    stored_classified = session.get(Document, classified_document.id)
    assert stored_classified is not None
    assert stored_classified.knowledge_space_id == space.id
    assert stored_classified.category_department_id == department.id
    assert stored_classified.knowledge_category_id == category.id


def test_knowledge_classification_migration_is_idempotent_against_create_all(
    monkeypatch,
):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from server.app.db.base import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    migration = importlib.import_module(
        "server.app.db.migrations.versions.0004_knowledge_classification"
    )

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        monkeypatch.setattr(migration, "op", operations)

        migration.upgrade()
        migration.upgrade()

    inspector = inspect(engine)
    document_indexes = {index["name"] for index in inspector.get_indexes("documents")}
    assert "idx_documents_tenant_space_updated" in document_indexes
    assert "idx_documents_tenant_category_department_updated" in document_indexes
    assert "idx_documents_tenant_knowledge_category_updated" in document_indexes


def test_alembic_upgrade_head_creates_knowledge_classification_schema(tmp_path):
    from server.app.core.config import settings

    db_path = tmp_path / "knowledge_classification.sqlite3"
    original_database_url = settings.database_url
    object.__setattr__(
        settings, "database_url", f"sqlite+pysqlite:///{db_path.as_posix()}"
    )
    try:
        config = Config("alembic.ini")
        command.upgrade(config, "head")
        command.upgrade(config, "head")
    finally:
        object.__setattr__(settings, "database_url", original_database_url)

    engine = create_engine(f"sqlite+pysqlite:///{db_path.as_posix()}")
    inspector = inspect(engine)
    assert "knowledge_spaces" in inspector.get_table_names()
    assert "knowledge_categories" in inspector.get_table_names()
    document_columns = {column["name"] for column in inspector.get_columns("documents")}
    assert {
        "knowledge_space_id",
        "category_department_id",
        "knowledge_category_id",
    }.issubset(document_columns)



def _seed_classification_service():
    from server.app.core.permissions import AccessContext
    from server.app.models.user import Department, Tenant
    from server.app.services.knowledge_category_service import KnowledgeCategoryService

    _engine, session = _build_session()
    tenant = Tenant(name="默认租户")
    session.add(tenant)
    session.flush()
    support = Department(tenant_id=tenant.id, name="Support", code="SUPPORT")
    private = Department(tenant_id=tenant.id, name="Private", code="PRIVATE")
    session.add_all([support, private])
    session.commit()
    context = AccessContext(
        tenant_id=tenant.id,
        user_id="admin-user",
        department_id=support.id,
        role_ids=[],
        permissions={"DOCUMENT_READ", "DOCUMENT_WRITE"},
    )
    return session, KnowledgeCategoryService(session), context, support, private


def test_knowledge_category_schemas_serialize_camel_case():
    from server.app.schemas.knowledge_category import (
        DocumentClassificationResponse,
        KnowledgeCategoryCreateRequest,
        KnowledgeSpaceResponse,
        NamedClassificationNodeResponse,
    )

    create_request = KnowledgeCategoryCreateRequest(
        spaceId="space-1",
        departmentId="dept-1",
        name="退款专题",
        code="refund",
        sortOrder=7,
    )
    assert create_request.space_id == "space-1"
    assert create_request.model_dump(by_alias=True)["spaceId"] == "space-1"
    assert create_request.model_dump(by_alias=True)["sortOrder"] == 7

    space_response = KnowledgeSpaceResponse(
        id="space-1",
        name="客服知识库",
        code="support-kb",
        description=None,
        status="ACTIVE",
        sort_order=3,
        created_at=None,
        updated_at=None,
    )
    assert space_response.model_dump(by_alias=True)["sortOrder"] == 3
    assert "sort_order" not in space_response.model_dump(by_alias=True)

    classification = DocumentClassificationResponse(
        knowledge_space_id="space-1",
        category_department_id="dept-1",
        knowledge_category_id="cat-1",
        knowledge_space=NamedClassificationNodeResponse(
            id="space-1", name="客服知识库", code="support-kb"
        ),
        category_department=NamedClassificationNodeResponse(
            id="dept-1", name="Support", code="SUPPORT"
        ),
        knowledge_category=NamedClassificationNodeResponse(
            id="cat-1", name="退款专题", code="refund"
        ),
    ).model_dump(by_alias=True)
    assert classification["knowledgeSpaceId"] == "space-1"
    assert classification["categoryDepartment"]["code"] == "SUPPORT"


def test_create_and_update_space_repository_and_service():
    from server.app.schemas.knowledge_category import (
        KnowledgeSpaceCreateRequest,
        KnowledgeSpaceUpdateRequest,
    )

    session, service, context, _support, _private = _seed_classification_service()

    created = service.create_space(
        context,
        KnowledgeSpaceCreateRequest(
            name=" 客服知识库 ", code="support-kb", sortOrder=10
        ),
    )
    assert created["name"] == "客服知识库"
    assert created["code"] == "support-kb"
    assert created["sort_order"] == 10
    assert service.spaces.get_for_tenant(context.tenant_id, created["id"]) is not None
    assert [space["id"] for space in service.list_spaces(context)] == [created["id"]]

    updated = service.update_space(
        context,
        created["id"],
        KnowledgeSpaceUpdateRequest(name="客服资料库", code="support-docs"),
    )
    assert updated["name"] == "客服资料库"
    assert updated["code"] == "support-docs"

    service.delete_space(context, created["id"])
    session.expire_all()
    assert service.spaces.get_for_tenant(context.tenant_id, created["id"]) is None


def test_duplicate_space_code_raises_conflict():
    from fastapi import HTTPException
    from server.app.schemas.knowledge_category import KnowledgeSpaceCreateRequest

    _session, service, context, _support, _private = _seed_classification_service()
    payload = KnowledgeSpaceCreateRequest(name="客服知识库", code="support-kb")
    service.create_space(context, payload)

    try:
        service.create_space(context, payload)
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail["error"]["code"] == "KNOWLEDGE_SPACE_CODE_EXISTS"
    else:
        raise AssertionError("duplicate space code should fail")


def test_create_and_update_category_repository_and_service():
    from server.app.models.knowledge_category import KnowledgeCategoryType
    from server.app.schemas.knowledge_category import (
        KnowledgeCategoryCreateRequest,
        KnowledgeCategoryUpdateRequest,
        KnowledgeSpaceCreateRequest,
    )

    _session, service, context, support, _private = _seed_classification_service()
    space = service.create_space(
        context, KnowledgeSpaceCreateRequest(name="客服知识库", code="support-kb")
    )
    category = service.create_category(
        context,
        KnowledgeCategoryCreateRequest(
            spaceId=space["id"],
            departmentId=support.id,
            name="退款专题",
            code="refund",
            categoryType=KnowledgeCategoryType.TOPIC,
        ),
    )
    assert category["space_id"] == space["id"]
    assert category["department_id"] == support.id
    assert category["category_type"] == KnowledgeCategoryType.TOPIC
    assert service.categories.get_for_tenant(
        context.tenant_id, category["id"]
    ) is not None
    assert [item["id"] for item in service.list_categories(context)] == [
        category["id"]
    ]
    assert [
        item["id"]
        for item in service.list_categories(
            context, space_id=space["id"], department_id=support.id
        )
    ] == [category["id"]]

    updated = service.update_category(
        context,
        category["id"],
        KnowledgeCategoryUpdateRequest(name="退款项目", categoryType="PROJECT"),
    )
    assert updated["name"] == "退款项目"
    assert updated["category_type"] == "PROJECT"

    service.delete_category(context, category["id"])
    assert service.categories.get_for_tenant(context.tenant_id, category["id"]) is None


def test_duplicate_category_code_in_same_space_and_department_raises_conflict():
    from fastapi import HTTPException
    from server.app.schemas.knowledge_category import (
        KnowledgeCategoryCreateRequest,
        KnowledgeSpaceCreateRequest,
    )

    _session, service, context, support, _private = _seed_classification_service()
    space = service.create_space(
        context, KnowledgeSpaceCreateRequest(name="客服知识库", code="support-kb")
    )
    payload = KnowledgeCategoryCreateRequest(
        spaceId=space["id"], departmentId=support.id, name="退款专题", code="refund"
    )
    service.create_category(context, payload)

    try:
        service.create_category(context, payload)
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail["error"]["code"] == "KNOWLEDGE_CATEGORY_CODE_EXISTS"
    else:
        raise AssertionError("duplicate category code should fail")


def test_create_category_requires_existing_space_and_department():
    from fastapi import HTTPException
    from server.app.schemas.knowledge_category import (
        KnowledgeCategoryCreateRequest,
        KnowledgeSpaceCreateRequest,
    )

    _session, service, context, support, _private = _seed_classification_service()
    missing_space_payload = KnowledgeCategoryCreateRequest(
        spaceId="missing-space", departmentId=support.id, name="退款专题", code="refund"
    )
    try:
        service.create_category(context, missing_space_payload)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("missing space should fail")

    space = service.create_space(
        context, KnowledgeSpaceCreateRequest(name="客服知识库", code="support-kb")
    )
    missing_department_payload = KnowledgeCategoryCreateRequest(
        spaceId=space["id"],
        departmentId="missing-department",
        name="退款专题",
        code="refund",
    )
    try:
        service.create_category(context, missing_department_payload)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("missing department should fail")


def test_validate_classification_accepts_valid_path_and_rejects_mismatch():
    from fastapi import HTTPException
    from server.app.schemas.knowledge_category import (
        DocumentClassificationRequest,
        KnowledgeCategoryCreateRequest,
        KnowledgeSpaceCreateRequest,
    )

    _session, service, context, support, private = _seed_classification_service()
    space = service.create_space(
        context, KnowledgeSpaceCreateRequest(name="客服知识库", code="support-kb")
    )
    category = service.create_category(
        context,
        KnowledgeCategoryCreateRequest(
            spaceId=space["id"], departmentId=support.id, name="退款专题", code="refund"
        ),
    )

    valid = service.validate_classification(
        context,
        DocumentClassificationRequest(
            knowledgeSpaceId=space["id"],
            categoryDepartmentId=support.id,
            knowledgeCategoryId=category["id"],
        ),
    )
    assert valid.knowledge_space is not None
    assert valid.category_department is not None
    assert valid.knowledge_category is not None
    assert valid.knowledge_category.id == category["id"]

    try:
        service.validate_classification(
            context,
            DocumentClassificationRequest(
                knowledgeSpaceId=space["id"],
                categoryDepartmentId=private.id,
                knowledgeCategoryId=category["id"],
            ),
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail["error"]["code"] == "CLASSIFICATION_PATH_INVALID"
    else:
        raise AssertionError("mismatched classification path should fail")


def test_delete_space_or_category_rejects_used_documents():
    from fastapi import HTTPException
    from server.app.models.document import Document, DocumentStatus
    from server.app.schemas.knowledge_category import (
        KnowledgeCategoryCreateRequest,
        KnowledgeSpaceCreateRequest,
    )

    session, service, context, support, _private = _seed_classification_service()
    space = service.create_space(
        context, KnowledgeSpaceCreateRequest(name="客服知识库", code="support-kb")
    )
    category = service.create_category(
        context,
        KnowledgeCategoryCreateRequest(
            spaceId=space["id"], departmentId=support.id, name="退款专题", code="refund"
        ),
    )
    session.add(
        Document(
            tenant_id=context.tenant_id,
            title="退款流程",
            file_name="refund.pdf",
            file_type="PDF",
            mime_type="application/pdf",
            file_size=200,
            object_key="documents/refund.pdf",
            checksum="refund",
            status=DocumentStatus.READY,
            knowledge_space_id=space["id"],
            category_department_id=support.id,
            knowledge_category_id=category["id"],
        )
    )
    session.commit()

    try:
        service.delete_category(context, category["id"])
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail["error"]["code"] == "KNOWLEDGE_CATEGORY_HAS_DOCUMENTS"
    else:
        raise AssertionError("used category should not be deleted")

    try:
        service.delete_space(context, space["id"])
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail["error"]["code"] == "KNOWLEDGE_SPACE_HAS_DOCUMENTS"
    else:
        raise AssertionError("used space should not be deleted")


def test_classification_to_dict_returns_named_nodes():
    from server.app.models.document import Document, DocumentStatus
    from server.app.schemas.knowledge_category import (
        KnowledgeCategoryCreateRequest,
        KnowledgeSpaceCreateRequest,
    )

    session, service, context, support, _private = _seed_classification_service()
    space = service.create_space(
        context, KnowledgeSpaceCreateRequest(name="客服知识库", code="support-kb")
    )
    category = service.create_category(
        context,
        KnowledgeCategoryCreateRequest(
            spaceId=space["id"], departmentId=support.id, name="退款专题", code="refund"
        ),
    )
    document = Document(
        tenant_id=context.tenant_id,
        title="退款流程",
        file_name="refund.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=200,
        object_key="documents/refund.pdf",
        checksum="refund",
        status=DocumentStatus.READY,
        knowledge_space_id=space["id"],
        category_department_id=support.id,
        knowledge_category_id=category["id"],
    )
    session.add(document)
    session.commit()

    serialized = service.classification_to_dict(context, document)
    assert serialized["knowledge_space"]["name"] == "客服知识库"
    assert serialized["category_department"]["code"] == "SUPPORT"
    assert serialized["knowledge_category"]["name"] == "退款专题"
