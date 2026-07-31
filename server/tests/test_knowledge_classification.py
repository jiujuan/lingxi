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



def test_category_document_migration_returns_count_and_allows_delete():
    from fastapi import HTTPException
    from server.app.models.document import Document, DocumentStatus
    from server.app.schemas.knowledge_category import (
        KnowledgeCategoryCreateRequest,
        KnowledgeSpaceCreateRequest,
        MigrateCategoryDocumentsRequest,
    )

    session, service, context, support, _private = _seed_classification_service()
    space = service.create_space(
        context, KnowledgeSpaceCreateRequest(name="客服知识库", code="support-kb")
    )
    source = service.create_category(
        context,
        KnowledgeCategoryCreateRequest(
            spaceId=space["id"], departmentId=support.id, name="退款专题", code="refund"
        ),
    )
    target = service.create_category(
        context,
        KnowledgeCategoryCreateRequest(
            spaceId=space["id"], departmentId=support.id, name="安装专题", code="install"
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
        knowledge_category_id=source["id"],
    )
    session.add(document)
    session.commit()

    try:
        service.delete_category(context, source["id"])
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail["error"]["code"] == "KNOWLEDGE_CATEGORY_HAS_DOCUMENTS"
        assert exc.detail["error"]["details"]["documentCount"] == 1
    else:
        raise AssertionError("used category should not be deleted")

    migrated = service.migrate_category_documents(
        context,
        source["id"],
        MigrateCategoryDocumentsRequest(
            targetSpaceId=space["id"],
            targetDepartmentId=support.id,
            targetCategoryId=target["id"],
        ),
    )
    assert migrated["migrated_count"] == 1
    assert migrated["target_classification"]["knowledge_category_id"] == target["id"]

    session.refresh(document)
    assert document.knowledge_space_id == space["id"]
    assert document.category_department_id == support.id
    assert document.knowledge_category_id == target["id"]

    service.delete_category(context, source["id"])
    assert service.categories.get_for_tenant(context.tenant_id, source["id"]) is None


def test_space_document_migration_requires_same_tenant_target_and_allows_delete():
    from fastapi import HTTPException
    from server.app.core.permissions import AccessContext
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.user import Department, Tenant
    from server.app.schemas.knowledge_category import (
        KnowledgeCategoryCreateRequest,
        KnowledgeSpaceCreateRequest,
        MigrateCategoryDocumentsRequest,
    )
    from server.app.services.knowledge_category_service import KnowledgeCategoryService

    session, service, context, support, _private = _seed_classification_service()
    source_space = service.create_space(
        context, KnowledgeSpaceCreateRequest(name="待迁移空间", code="source-kb")
    )
    target_space = service.create_space(
        context, KnowledgeSpaceCreateRequest(name="目标空间", code="target-kb")
    )
    target_category = service.create_category(
        context,
        KnowledgeCategoryCreateRequest(
            spaceId=target_space["id"],
            departmentId=support.id,
            name="目标专题",
            code="target-topic",
        ),
    )
    document = Document(
        tenant_id=context.tenant_id,
        title="待迁移文档",
        file_name="source.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=200,
        object_key="documents/source.pdf",
        checksum="source",
        status=DocumentStatus.READY,
        knowledge_space_id=source_space["id"],
        category_department_id=support.id,
    )
    session.add(document)

    other_tenant = Tenant(name="其他租户")
    session.add(other_tenant)
    session.flush()
    other_department = Department(tenant_id=other_tenant.id, name="Other", code="OTHER")
    session.add(other_department)
    session.commit()
    other_context = AccessContext(
        tenant_id=other_tenant.id,
        user_id="other-admin",
        department_id=other_department.id,
        role_ids=[],
        permissions={"DOCUMENT_READ", "DOCUMENT_WRITE"},
    )
    other_service = KnowledgeCategoryService(session)
    other_space = other_service.create_space(
        other_context, KnowledgeSpaceCreateRequest(name="其他空间", code="other-kb")
    )
    other_category = other_service.create_category(
        other_context,
        KnowledgeCategoryCreateRequest(
            spaceId=other_space["id"],
            departmentId=other_department.id,
            name="其他专题",
            code="other-topic",
        ),
    )

    try:
        service.migrate_space_documents(
            context,
            source_space["id"],
            MigrateCategoryDocumentsRequest(
                targetSpaceId=other_space["id"],
                targetDepartmentId=other_department.id,
                targetCategoryId=other_category["id"],
            ),
        )
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("cross-tenant target should not be accepted")

    migrated = service.migrate_space_documents(
        context,
        source_space["id"],
        MigrateCategoryDocumentsRequest(
            targetSpaceId=target_space["id"],
            targetDepartmentId=support.id,
            targetCategoryId=target_category["id"],
        ),
    )
    assert migrated["migrated_count"] == 1
    session.refresh(document)
    assert document.knowledge_space_id == target_space["id"]
    assert document.knowledge_category_id == target_category["id"]

    service.delete_space(context, source_space["id"])
    assert service.spaces.get_for_tenant(context.tenant_id, source_space["id"]) is None

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


def _login_admin_headers(client) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "Admin123!"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def _login_employee_headers(client) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "employee@example.com", "password": "Employee123!"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


def _department_ids(SessionLocal) -> dict[str, str]:
    from server.app.models.user import Department

    with SessionLocal() as session:
        return {
            department.code: department.id
            for department in session.scalars(select(Department)).all()
        }


def test_knowledge_classification_openapi_contains_management_paths():
    from server.tests.test_auth_rbac import build_test_client

    client, _SessionLocal = build_test_client()
    schema = client.get("/openapi.json").json()

    assert "/api/v1/knowledge-spaces" in schema["paths"]
    assert "/api/v1/knowledge-spaces/stats" in schema["paths"]
    assert "/api/v1/knowledge-spaces/{space_id}" in schema["paths"]
    assert "/api/v1/knowledge-spaces/{space_id}/migrate-documents" in schema["paths"]
    assert "/api/v1/knowledge-categories" in schema["paths"]
    assert "/api/v1/knowledge-categories/stats" in schema["paths"]
    assert "/api/v1/knowledge-categories/{category_id}/migrate-documents" in schema["paths"]
    assert "/api/v1/knowledge-categories/{category_id}" in schema["paths"]


def test_admin_can_crud_knowledge_spaces_over_http():
    from server.tests.test_auth_rbac import build_test_client

    client, _SessionLocal = build_test_client()
    headers = _login_admin_headers(client)

    created = client.post(
        "/api/v1/knowledge-spaces",
        headers=headers,
        json={
            "name": "客服知识库",
            "code": "support-kb",
            "description": "客服团队使用",
            "sortOrder": 2,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "客服知识库"
    assert body["sortOrder"] == 2
    assert "sort_order" not in body

    listed = client.get("/api/v1/knowledge-spaces", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [body["id"]]

    updated = client.put(
        f"/api/v1/knowledge-spaces/{body['id']}",
        headers=headers,
        json={"name": "客服资料库", "code": "support-docs"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "客服资料库"
    assert updated.json()["code"] == "support-docs"

    deleted = client.delete(f"/api/v1/knowledge-spaces/{body['id']}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    assert client.get("/api/v1/knowledge-spaces", headers=headers).json()["data"] == []


def test_admin_can_crud_and_filter_knowledge_categories_over_http():
    from server.tests.test_auth_rbac import build_test_client

    client, SessionLocal = build_test_client()
    headers = _login_admin_headers(client)
    departments = _department_ids(SessionLocal)
    support_id = departments["SUPPORT"]
    private_id = departments["PRIVATE"]

    space = client.post(
        "/api/v1/knowledge-spaces",
        headers=headers,
        json={"name": "客服知识库", "code": "support-kb"},
    ).json()
    other_space = client.post(
        "/api/v1/knowledge-spaces",
        headers=headers,
        json={"name": "内部知识库", "code": "internal-kb"},
    ).json()
    category = client.post(
        "/api/v1/knowledge-categories",
        headers=headers,
        json={
            "spaceId": space["id"],
            "departmentId": support_id,
            "name": "退款专题",
            "code": "refund",
            "categoryType": "TOPIC",
            "sortOrder": 5,
        },
    )
    assert category.status_code == 201
    body = category.json()
    assert body["spaceId"] == space["id"]
    assert body["departmentId"] == support_id
    assert body["categoryType"] == "TOPIC"
    assert body["sortOrder"] == 5

    second = client.post(
        "/api/v1/knowledge-categories",
        headers=headers,
        json={
            "spaceId": other_space["id"],
            "departmentId": private_id,
            "name": "内部制度",
            "code": "policy",
        },
    ).json()

    listed_by_space = client.get(
        "/api/v1/knowledge-categories",
        headers=headers,
        params={"spaceId": space["id"]},
    )
    assert listed_by_space.status_code == 200
    assert [item["id"] for item in listed_by_space.json()["data"]] == [body["id"]]

    listed_by_department = client.get(
        "/api/v1/knowledge-categories",
        headers=headers,
        params={"departmentId": private_id},
    )
    assert listed_by_department.status_code == 200
    assert [item["id"] for item in listed_by_department.json()["data"]] == [
        second["id"]
    ]

    updated = client.put(
        f"/api/v1/knowledge-categories/{body['id']}",
        headers=headers,
        json={"name": "退款项目", "categoryType": "PROJECT"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "退款项目"
    assert updated.json()["categoryType"] == "PROJECT"

    deleted = client.delete(
        f"/api/v1/knowledge-categories/{body['id']}", headers=headers
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}


def test_knowledge_classification_api_error_mapping_and_permissions():
    from server.tests.test_auth_rbac import build_test_client

    client, SessionLocal = build_test_client()
    admin_headers = _login_admin_headers(client)
    employee_headers = _login_employee_headers(client)
    support_id = _department_ids(SessionLocal)["SUPPORT"]

    unauthorized_write = client.post(
        "/api/v1/knowledge-spaces",
        headers=employee_headers,
        json={"name": "客服知识库", "code": "support-kb"},
    )
    assert unauthorized_write.status_code == 403
    assert unauthorized_write.json()["error"]["code"] == "FORBIDDEN"

    space = client.post(
        "/api/v1/knowledge-spaces",
        headers=admin_headers,
        json={"name": "客服知识库", "code": "support-kb"},
    ).json()
    duplicate = client.post(
        "/api/v1/knowledge-spaces",
        headers=admin_headers,
        json={"name": "客服知识库", "code": "support-kb"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "KNOWLEDGE_SPACE_CODE_EXISTS"

    missing_space_category = client.post(
        "/api/v1/knowledge-categories",
        headers=admin_headers,
        json={
            "spaceId": "missing-space",
            "departmentId": support_id,
            "name": "退款专题",
            "code": "refund",
        },
    )
    assert missing_space_category.status_code == 404
    assert missing_space_category.json()["error"]["code"] == "NOT_FOUND"

    missing_filter = client.get(
        "/api/v1/knowledge-categories",
        headers=admin_headers,
        params={"spaceId": "missing-space"},
    )
    assert missing_filter.status_code == 404

    category = client.post(
        "/api/v1/knowledge-categories",
        headers=admin_headers,
        json={
            "spaceId": space["id"],
            "departmentId": support_id,
            "name": "退款专题",
            "code": "refund",
        },
    ).json()
    duplicate_category = client.post(
        "/api/v1/knowledge-categories",
        headers=admin_headers,
        json={
            "spaceId": space["id"],
            "departmentId": support_id,
            "name": "退款专题",
            "code": "refund",
        },
    )
    assert duplicate_category.status_code == 409
    assert duplicate_category.json()["error"]["code"] == (
        "KNOWLEDGE_CATEGORY_CODE_EXISTS"
    )

    assert client.delete(
        f"/api/v1/knowledge-categories/{category['id']}", headers=employee_headers
    ).status_code == 403

def test_classification_stats_service_counts_documents_by_status_and_scope():
    from datetime import datetime, timezone

    from server.app.models.document import Document, DocumentStatus
    from server.app.models.user import Tenant
    from server.app.schemas.knowledge_category import (
        KnowledgeCategoryCreateRequest,
        KnowledgeSpaceCreateRequest,
    )

    session, service, context, support, _private = _seed_classification_service()
    space = service.create_space(
        context, KnowledgeSpaceCreateRequest(name="客服知识库", code="support-kb")
    )
    refund = service.create_category(
        context,
        KnowledgeCategoryCreateRequest(
            spaceId=space["id"], departmentId=support.id, name="退款专题", code="refund"
        ),
    )
    invoice = service.create_category(
        context,
        KnowledgeCategoryCreateRequest(
            spaceId=space["id"], departmentId=support.id, name="发票专题", code="invoice"
        ),
    )
    other_tenant = Tenant(name="其他租户")
    session.add(other_tenant)
    session.flush()

    def document(title, status, category_id=None, tenant_id=context.tenant_id, deleted=False):
        return Document(
            tenant_id=tenant_id,
            title=title,
            file_name=f"{title}.pdf",
            file_type="PDF",
            mime_type="application/pdf",
            file_size=100,
            object_key=f"documents/{title}.pdf",
            checksum=title,
            status=status,
            knowledge_space_id=space["id"] if tenant_id == context.tenant_id else "foreign-space",
            category_department_id=support.id if tenant_id == context.tenant_id else None,
            knowledge_category_id=category_id,
            deleted_at=datetime.now(timezone.utc) if deleted else None,
        )

    session.add_all(
        [
            document("refund-ready", DocumentStatus.READY, refund["id"]),
            document("refund-failed", DocumentStatus.FAILED, refund["id"]),
            document("invoice-parsing", DocumentStatus.PARSING, invoice["id"]),
            document("space-unclassified", DocumentStatus.READY),
            document("deleted-ready", DocumentStatus.READY, refund["id"], deleted=True),
            document("status-deleted", DocumentStatus.DELETED, refund["id"]),
            document("foreign-ready", DocumentStatus.READY, refund["id"], tenant_id=other_tenant.id),
        ]
    )
    session.add(
        Document(
            tenant_id=context.tenant_id,
            title="global-unclassified",
            file_name="global-unclassified.pdf",
            file_type="PDF",
            mime_type="application/pdf",
            file_size=100,
            object_key="documents/global-unclassified.pdf",
            checksum="global-unclassified",
            status=DocumentStatus.UPLOADED,
        )
    )
    session.commit()

    space_stats = service.list_space_stats(context)
    assert space_stats["summary"] == {
        "total_count": 2,
        "processing_count": 1,
        "ready_count": 1,
        "failed_count": 0,
        "unclassified_count": 2,
    }
    assert space_stats["data"] == [
        {
            "space_id": space["id"],
            "total_count": 4,
            "processing_count": 1,
            "ready_count": 2,
            "failed_count": 1,
            "unclassified_count": 1,
        }
    ]

    category_stats = service.list_category_stats(
        context, space_id=space["id"], department_id=support.id
    )
    stats_by_id = {item["category_id"]: item for item in category_stats["data"]}
    assert stats_by_id[refund["id"]]["total_count"] == 2
    assert stats_by_id[refund["id"]]["ready_count"] == 1
    assert stats_by_id[refund["id"]]["failed_count"] == 1
    assert stats_by_id[invoice["id"]]["total_count"] == 1
    assert stats_by_id[invoice["id"]]["processing_count"] == 1
    assert category_stats["unclassified"]["total_count"] == 1
    assert category_stats["unclassified"]["unclassified_count"] == 1



def test_classification_migration_api_moves_documents_and_unblocks_delete():
    from server.app.models.document import Document, DocumentStatus
    from server.tests.test_auth_rbac import build_test_client

    client, SessionLocal = build_test_client()
    headers = _login_admin_headers(client)
    support_id = _department_ids(SessionLocal)["SUPPORT"]

    space = client.post(
        "/api/v1/knowledge-spaces",
        headers=headers,
        json={"name": "客服知识库", "code": "support-kb"},
    ).json()
    source = client.post(
        "/api/v1/knowledge-categories",
        headers=headers,
        json={
            "spaceId": space["id"],
            "departmentId": support_id,
            "name": "退款专题",
            "code": "refund",
        },
    ).json()
    target = client.post(
        "/api/v1/knowledge-categories",
        headers=headers,
        json={
            "spaceId": space["id"],
            "departmentId": support_id,
            "name": "安装专题",
            "code": "install",
        },
    ).json()
    with SessionLocal() as session:
        tenant_id = session.scalar(select(Document.tenant_id))
        if tenant_id is None:
            from server.app.models.user import Tenant

            tenant_id = session.scalar(select(Tenant.id))
        session.add(
            Document(
                tenant_id=tenant_id,
                title="退款流程",
                file_name="refund.pdf",
                file_type="PDF",
                mime_type="application/pdf",
                file_size=200,
                object_key="documents/refund.pdf",
                checksum="refund",
                status=DocumentStatus.READY,
                knowledge_space_id=space["id"],
                category_department_id=support_id,
                knowledge_category_id=source["id"],
            )
        )
        session.commit()

    blocked = client.delete(
        f"/api/v1/knowledge-categories/{source['id']}", headers=headers
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["details"]["documentCount"] == 1

    migrated = client.post(
        f"/api/v1/knowledge-categories/{source['id']}/migrate-documents",
        headers=headers,
        json={
            "targetSpaceId": space["id"],
            "targetDepartmentId": support_id,
            "targetCategoryId": target["id"],
        },
    )
    assert migrated.status_code == 200
    assert migrated.json()["migratedCount"] == 1
    assert migrated.json()["targetClassification"]["knowledgeCategoryId"] == target["id"]

    with SessionLocal() as session:
        stored = session.scalar(select(Document).where(Document.title == "退款流程"))
        assert stored.knowledge_category_id == target["id"]

    deleted = client.delete(
        f"/api/v1/knowledge-categories/{source['id']}", headers=headers
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}

def test_classification_stats_api_returns_space_category_and_unclassified_counts():
    from server.app.models.document import Document, DocumentStatus
    from server.tests.test_auth_rbac import build_test_client

    client, SessionLocal = build_test_client()
    headers = _login_admin_headers(client)
    support_id = _department_ids(SessionLocal)["SUPPORT"]

    space = client.post(
        "/api/v1/knowledge-spaces",
        headers=headers,
        json={"name": "客服知识库", "code": "support-kb"},
    ).json()
    category = client.post(
        "/api/v1/knowledge-categories",
        headers=headers,
        json={
            "spaceId": space["id"],
            "departmentId": support_id,
            "name": "退款专题",
            "code": "refund",
        },
    ).json()
    with SessionLocal() as session:
        tenant_id = session.scalar(select(Document.tenant_id))
        if tenant_id is None:
            from server.app.models.user import Tenant

            tenant_id = session.scalar(select(Tenant.id))
        session.add_all(
            [
                Document(
                    tenant_id=tenant_id,
                    title="退款流程",
                    file_name="refund.pdf",
                    file_type="PDF",
                    mime_type="application/pdf",
                    file_size=200,
                    object_key="documents/refund.pdf",
                    checksum="refund",
                    status=DocumentStatus.READY,
                    knowledge_space_id=space["id"],
                    category_department_id=support_id,
                    knowledge_category_id=category["id"],
                ),
                Document(
                    tenant_id=tenant_id,
                    title="未分类",
                    file_name="unclassified.pdf",
                    file_type="PDF",
                    mime_type="application/pdf",
                    file_size=100,
                    object_key="documents/unclassified.pdf",
                    checksum="unclassified",
                    status=DocumentStatus.FAILED,
                    knowledge_space_id=space["id"],
                    category_department_id=support_id,
                ),
            ]
        )
        session.commit()

    space_stats = client.get("/api/v1/knowledge-spaces/stats", headers=headers)
    assert space_stats.status_code == 200
    space_stat = space_stats.json()["data"][0]
    assert space_stat["spaceId"] == space["id"]
    assert space_stat["totalCount"] == 2
    assert space_stat["readyCount"] == 1
    assert space_stat["failedCount"] == 1
    assert space_stat["unclassifiedCount"] == 1
    assert space_stats.json()["summary"]["unclassifiedCount"] == 1

    category_stats = client.get(
        "/api/v1/knowledge-categories/stats",
        headers=headers,
        params={"spaceId": space["id"], "departmentId": support_id},
    )
    assert category_stats.status_code == 200
    category_body = category_stats.json()
    assert category_body["data"][0]["categoryId"] == category["id"]
    assert category_body["data"][0]["totalCount"] == 1
    assert category_body["unclassified"]["totalCount"] == 1

    assert client.get("/api/v1/knowledge-spaces/stats").status_code in {401, 403}


def test_chunk_sqlite_fallback_scopes_before_sorting_and_excludes_deleted_document():
    from datetime import UTC, datetime

    from server.app.core.permissions import AccessContext
    from server.app.models.document import (
        Document,
        DocumentAccessRule,
        DocumentAccessSubjectType,
        DocumentStatus,
    )
    from server.app.models.qa_pair import DocumentChunk
    from server.app.repositories.retrieval_repo import RetrievalRepository
    from server.tests.test_document_permissions import build_session

    session, identity = build_session()
    tenant_id = identity["tenant"].id
    context = AccessContext(
        tenant_id=tenant_id,
        user_id=identity["users"]["employee"].id,
        department_id=identity["departments"]["support"].id,
        role_ids=[identity["roles"]["employee"].id],
        permissions={"DOCUMENT_READ"},
    )
    visible = Document(
        tenant_id=tenant_id,
        title="Visible",
        file_name="visible.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=1,
        object_key="documents/visible.pdf",
        checksum="visible",
        status=DocumentStatus.READY,
    )
    deleted = Document(
        tenant_id=tenant_id,
        title="Deleted",
        file_name="deleted.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=1,
        object_key="documents/deleted.pdf",
        checksum="deleted",
        status=DocumentStatus.READY,
        deleted_at=datetime.now(UTC),
    )
    session.add_all([visible, deleted])
    session.flush()
    session.add(
        DocumentAccessRule(
            tenant_id=tenant_id,
            document_id=visible.id,
            subject_type=DocumentAccessSubjectType.DEPARTMENT,
            subject_id=context.department_id,
        )
    )
    visible_parent = DocumentChunk(
        tenant_id=tenant_id,
        document_id=visible.id,
        chunk_index=0,
        content="parent",
        chunk_level="PARENT",
        status="ACTIVE",
    )
    deleted_parent = DocumentChunk(
        tenant_id=tenant_id,
        document_id=deleted.id,
        chunk_index=0,
        content="parent",
        chunk_level="PARENT",
        status="ACTIVE",
    )
    visible_child = DocumentChunk(
        tenant_id=tenant_id,
        document_id=visible.id,
        chunk_index=1,
        content="refund policy",
        search_text="refund policy",
        chunk_level="CHILD",
        parent_chunk=visible_parent,
        status="ACTIVE",
        embedding=[0.5, 0.5],
    )
    deleted_child = DocumentChunk(
        tenant_id=tenant_id,
        document_id=deleted.id,
        chunk_index=1,
        content="refund refund refund",
        search_text="refund refund refund",
        chunk_level="CHILD",
        parent_chunk=deleted_parent,
        status="ACTIVE",
        embedding=[1.0, 0.0],
    )
    session.add_all([visible_parent, deleted_parent, visible_child, deleted_child])
    session.commit()

    # SQLite uses Python scoring. The deleted record scores higher, so returning
    # only the visible result proves authorization/deletion scope is applied before
    # top-k sorting.
    results = RetrievalRepository(session).search_chunk_vector(context, [1.0, 0.0], 1)

    assert [chunk.id for chunk, _score in results] == [visible_child.id]
