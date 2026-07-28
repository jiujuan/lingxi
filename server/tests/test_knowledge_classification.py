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
