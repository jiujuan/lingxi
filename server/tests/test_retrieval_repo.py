import server.app.db.base  # noqa: F401  (ensure mappers load before repo import)
from server.app.repositories.retrieval_repo import RetrievalRepository


def test_build_tsquery_sanitizes_and_dedupes_tokens():
    build = RetrievalRepository._build_tsquery
    # operators/punctuation stripped, CJK + alnum kept, duplicates removed, OR-joined
    assert build(["退款", "退款", "&", "SOP", "!!!"]) == "退款 | sop"
    assert build([":", "|", "()"]) == ""
    assert build([]) == ""


def test_build_tsquery_splits_mixed_tokens():
    # a raw token containing separators is split into safe lexemes
    assert RetrievalRepository._build_tsquery(["a-b.c"]) == "a | b | c"


def test_retrieval_access_scope_request_uses_camel_case_aliases():
    from server.app.schemas.retrieval import RetrievalAccessScopeRequest

    request = RetrievalAccessScopeRequest.model_validate(
        {
            "spaceId": "space-1",
            "classificationDepartmentId": "dept-1",
            "categoryId": "cat-1",
        }
    )
    scope = request.to_access_scope(document_ids={"doc-1"})

    assert request.model_dump(by_alias=True) == {
        "spaceId": "space-1",
        "classificationDepartmentId": "dept-1",
        "categoryId": "cat-1",
    }
    assert scope.document_ids == {"doc-1"}
    assert scope.space_id == "space-1"
    assert scope.classification_department_id == "dept-1"
    assert scope.category_id == "cat-1"


def _filter_value(expression):
    return expression.right.value


def test_build_classification_filters_omits_empty_scope():
    from server.app.repositories.retrieval_repo import RetrievalRepository

    assert RetrievalRepository._build_classification_filters(None) == []


def test_build_classification_filters_supports_space_department_and_category_granularity():
    from server.app.models.document import Document
    from server.app.repositories.retrieval_repo import RetrievalRepository
    from server.app.schemas.retrieval import RetrievalAccessScope

    space_filters = RetrievalRepository._build_classification_filters(
        RetrievalAccessScope(space_id="space-1")
    )
    assert len(space_filters) == 1
    assert space_filters[0].left.name == Document.knowledge_space_id.name
    assert _filter_value(space_filters[0]) == "space-1"

    department_filters = RetrievalRepository._build_classification_filters(
        RetrievalAccessScope(
            space_id="space-1", classification_department_id="dept-1"
        )
    )
    assert len(department_filters) == 2
    assert department_filters[0].left.name == Document.knowledge_space_id.name
    assert _filter_value(department_filters[0]) == "space-1"
    assert department_filters[1].left.name == Document.category_department_id.name
    assert _filter_value(department_filters[1]) == "dept-1"

    category_filters = RetrievalRepository._build_classification_filters(
        RetrievalAccessScope(
            space_id="space-1",
            classification_department_id="dept-1",
            category_id="cat-1",
        )
    )
    assert len(category_filters) == 3
    assert category_filters[0].left.name == Document.knowledge_space_id.name
    assert _filter_value(category_filters[0]) == "space-1"
    assert category_filters[1].left.name == Document.category_department_id.name
    assert _filter_value(category_filters[1]) == "dept-1"
    assert category_filters[2].left.name == Document.knowledge_category_id.name
    assert _filter_value(category_filters[2]) == "cat-1"


def test_filters_and_classification_with_document_access_predicates():
    from sqlalchemy import and_

    from server.app.core.permissions import AccessContext
    from server.app.models.document import Document
    from server.app.repositories.retrieval_repo import RetrievalRepository
    from server.app.schemas.retrieval import RetrievalAccessScope
    from server.tests.test_document_permissions import build_session

    session, identity = build_session()
    context = AccessContext(
        tenant_id=identity["tenant"].id,
        user_id=identity["users"]["employee"].id,
        department_id=identity["departments"]["support"].id,
        role_ids=[identity["roles"]["employee"].id],
        permissions={"DOCUMENT_READ"},
    )
    repo = RetrievalRepository(session)

    filters = repo._filters(
        context,
        RetrievalAccessScope(
            document_ids={"doc-1"},
            space_id="space-1",
            classification_department_id="dept-1",
            category_id="cat-1",
        ),
    )
    compiled = str(and_(*filters).compile(compile_kwargs={"literal_binds": True}))

    assert "EXISTS" in compiled
    assert "qa_pairs.document_id IN ('doc-1')" in compiled
    assert filters[-3].left.name == Document.knowledge_space_id.name
    assert filters[-2].left.name == Document.category_department_id.name
    assert filters[-1].left.name == Document.knowledge_category_id.name


def _retrieval_context(identity):
    from server.app.core.permissions import AccessContext

    return AccessContext(
        tenant_id=identity["tenant"].id,
        user_id=identity["users"]["employee"].id,
        department_id=identity["departments"]["support"].id,
        role_ids=[identity["roles"]["employee"].id],
        permissions={"DOCUMENT_READ"},
    )


def _add_readable_document(session, identity, *, title="Chunk document"):
    from server.app.models.document import (
        Document,
        DocumentAccessRule,
        DocumentAccessSubjectType,
        DocumentStatus,
    )

    document = Document(
        tenant_id=identity["tenant"].id,
        title=title,
        file_name="chunk.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=1,
        object_key="documents/chunk.pdf",
        checksum=title,
        status=DocumentStatus.READY,
    )
    session.add(document)
    session.flush()
    session.add(
        DocumentAccessRule(
            tenant_id=document.tenant_id,
            document_id=document.id,
            subject_type=DocumentAccessSubjectType.DEPARTMENT,
            subject_id=identity["departments"]["support"].id,
        )
    )
    return document


def test_chunk_vector_returns_only_live_active_children():
    from datetime import UTC, datetime

    from server.app.models.qa_pair import DocumentChunk, QaPair
    from server.tests.test_document_permissions import build_session

    session, identity = build_session()
    document = _add_readable_document(session, identity)
    parent = DocumentChunk(
        tenant_id=document.tenant_id,
        document_id=document.id,
        chunk_index=0,
        content="parent",
        chunk_level="PARENT",
        status="ACTIVE",
    )
    active_child = DocumentChunk(
        tenant_id=document.tenant_id,
        document_id=document.id,
        chunk_index=1,
        content="active child",
        chunk_level="CHILD",
        parent_chunk=parent,
        status="ACTIVE",
        embedding=[1.0, 0.0],
    )
    inactive_child = DocumentChunk(
        tenant_id=document.tenant_id,
        document_id=document.id,
        chunk_index=2,
        content="inactive child",
        chunk_level="CHILD",
        parent_chunk=parent,
        status="SUPERSEDED",
        embedding=[1.0, 0.0],
    )
    deleted_child = DocumentChunk(
        tenant_id=document.tenant_id,
        document_id=document.id,
        chunk_index=3,
        content="deleted child",
        chunk_level="CHILD",
        parent_chunk=parent,
        status="ACTIVE",
        deleted_at=datetime.now(UTC),
        embedding=[1.0, 0.0],
    )
    deleted_parent = DocumentChunk(
        tenant_id=document.tenant_id,
        document_id=document.id,
        chunk_index=4,
        content="deleted parent",
        chunk_level="PARENT",
        status="ACTIVE",
        deleted_at=datetime.now(UTC),
    )
    child_of_deleted_parent = DocumentChunk(
        tenant_id=document.tenant_id,
        document_id=document.id,
        chunk_index=5,
        content="orphaned from deleted parent",
        chunk_level="CHILD",
        parent_chunk=deleted_parent,
        status="ACTIVE",
        embedding=[1.0, 0.0],
    )
    session.add_all(
        [
            parent,
            active_child,
            inactive_child,
            deleted_child,
            deleted_parent,
            child_of_deleted_parent,
        ]
    )
    session.flush()
    session.add_all(
        [
            QaPair(
                tenant_id=document.tenant_id,
                document_id=document.id,
                chunk_id=active_child.id,
                pair_index=1,
                question="active child QA",
                answer="answer",
                question_embedding=[1.0, 0.0],
                status="ACTIVE",
            ),
            QaPair(
                tenant_id=document.tenant_id,
                document_id=document.id,
                chunk_id=inactive_child.id,
                pair_index=2,
                question="inactive child QA",
                answer="answer",
                question_embedding=[1.0, 0.0],
                status="ACTIVE",
            ),
            QaPair(
                tenant_id=document.tenant_id,
                document_id=document.id,
                chunk_id=child_of_deleted_parent.id,
                pair_index=3,
                question="deleted parent QA",
                answer="answer",
                question_embedding=[1.0, 0.0],
                status="ACTIVE",
            ),
        ]
    )
    session.commit()

    repo = RetrievalRepository(session)
    results = repo.search_chunk_vector(
        _retrieval_context(identity), [1.0, 0.0], top_k=10
    )
    qa_results = repo.search_qa_vector(
        _retrieval_context(identity), [1.0, 0.0], top_k=10
    )

    assert [chunk.id for chunk, _score in results] == [active_child.id]
    assert [pair.question for pair, _score in qa_results] == ["active child QA"]


def test_chunk_text_search_matches_title_path_and_content():
    from server.app.models.qa_pair import DocumentChunk
    from server.tests.test_document_permissions import build_session

    session, identity = build_session()
    document = _add_readable_document(session, identity)
    parent = DocumentChunk(
        tenant_id=document.tenant_id,
        document_id=document.id,
        chunk_index=0,
        content="parent",
        chunk_level="PARENT",
        status="ACTIVE",
    )
    title_path_hit = DocumentChunk(
        tenant_id=document.tenant_id,
        document_id=document.id,
        chunk_index=1,
        title_path=["退款", "售后流程"],
        content="常规内容",
        search_text="退款 售后流程 常规内容",
        chunk_level="CHILD",
        parent_chunk=parent,
        status="ACTIVE",
    )
    content_hit = DocumentChunk(
        tenant_id=document.tenant_id,
        document_id=document.id,
        chunk_index=2,
        title_path=["其他"],
        content="设备安装操作说明",
        search_text="其他 设备安装操作说明",
        chunk_level="CHILD",
        parent_chunk=parent,
        status="ACTIVE",
    )
    session.add_all([parent, title_path_hit, content_hit])
    session.commit()
    repo = RetrievalRepository(session)

    title_results = repo.search_chunk_text(
        _retrieval_context(identity), ["退款"], "退款", top_k=10
    )
    content_results = repo.search_chunk_text(
        _retrieval_context(identity), ["安装"], "安装", top_k=10
    )

    assert [chunk.id for chunk, _score in title_results] == [title_path_hit.id]
    assert [chunk.id for chunk, _score in content_results] == [content_hit.id]


def test_sqlite_searches_apply_score_then_shared_deterministic_tiebreakers(monkeypatch):
    from types import SimpleNamespace

    from server.tests.test_document_permissions import build_session

    session, identity = build_session()
    repo = RetrievalRepository(session)
    context = _retrieval_context(identity)
    qa_rows = [
        SimpleNamespace(
            id="qa-z",
            document_id="doc-1",
            pair_index=0,
            question_embedding=[1.0, 0.0],
            search_text="共同术语",
            question="共同术语",
        ),
        SimpleNamespace(
            id="qa-a",
            document_id="doc-1",
            pair_index=0,
            question_embedding=[1.0, 0.0],
            search_text="共同术语",
            question="共同术语",
        ),
        SimpleNamespace(
            id="qa-b",
            document_id="doc-1",
            pair_index=1,
            question_embedding=[1.0, 0.0],
            search_text="共同术语",
            question="共同术语",
        ),
        SimpleNamespace(
            id="qa-c",
            document_id="doc-2",
            pair_index=0,
            question_embedding=[1.0, 0.0],
            search_text="共同术语",
            question="共同术语",
        ),
    ]
    chunk_rows = [
        SimpleNamespace(
            id="chunk-z",
            document_id="doc-1",
            chunk_index=0,
            embedding=[1.0, 0.0],
            search_text="共同术语",
            content="共同术语",
        ),
        SimpleNamespace(
            id="chunk-a",
            document_id="doc-1",
            chunk_index=0,
            embedding=[1.0, 0.0],
            search_text="共同术语",
            content="共同术语",
        ),
        SimpleNamespace(
            id="chunk-b",
            document_id="doc-1",
            chunk_index=1,
            embedding=[1.0, 0.0],
            search_text="共同术语",
            content="共同术语",
        ),
        SimpleNamespace(
            id="chunk-c",
            document_id="doc-2",
            chunk_index=0,
            embedding=[1.0, 0.0],
            search_text="共同术语",
            content="共同术语",
        ),
    ]
    monkeypatch.setattr(repo, "list_authorized_qa_candidates", lambda *_args: qa_rows)
    monkeypatch.setattr(
        repo, "list_authorized_chunk_candidates", lambda *_args: chunk_rows
    )

    qa_vector = repo.search_qa_vector(context, [1.0, 0.0], top_k=4)
    qa_text = repo.search_qa_text(context, ["共同术语"], "共同术语", top_k=4)
    chunk_vector = repo.search_chunk_vector(context, [1.0, 0.0], top_k=4)
    chunk_text = repo.search_chunk_text(
        context, ["共同术语"], "共同术语", top_k=4
    )

    assert [item.id for item, _score in qa_vector] == [
        "qa-a",
        "qa-z",
        "qa-b",
        "qa-c",
    ]
    assert [item.id for item, _score in qa_text] == [
        "qa-a",
        "qa-z",
        "qa-b",
        "qa-c",
    ]
    assert [item.id for item, _score in chunk_vector] == [
        "chunk-a",
        "chunk-z",
        "chunk-b",
        "chunk-c",
    ]
    assert [item.id for item, _score in chunk_text] == [
        "chunk-a",
        "chunk-z",
        "chunk-b",
        "chunk-c",
    ]


def test_postgres_searches_include_deterministic_secondary_ordering():
    from sqlalchemy.dialects import postgresql

    from server.app.models.qa_pair import DocumentChunk, QaPair

    class _EmptyResult:
        @staticmethod
        def all():
            return []

    class _CapturingSession:
        def __init__(self):
            self.statements = []

        def execute(self, statement):
            self.statements.append(statement)
            return _EmptyResult()

    session = _CapturingSession()
    repo = RetrievalRepository(session)
    repo._vector_search_pg(QaPair, QaPair.question_embedding, [], [1.0, 0.0], 3)
    repo._text_search_pg(QaPair, [], ["term"], 3)
    repo._vector_search_pg(DocumentChunk, DocumentChunk.embedding, [], [1.0, 0.0], 3)
    repo._text_search_pg(DocumentChunk, [], ["term"], 3)

    sql = [
        str(statement.compile(dialect=postgresql.dialect()))
        for statement in session.statements
    ]
    for statement, table_name, index_name in zip(
        sql,
        ["qa_pairs", "qa_pairs", "document_chunks", "document_chunks"],
        ["pair_index", "pair_index", "chunk_index", "chunk_index"],
        strict=True,
    ):
        assert f"{table_name}.document_id ASC" in statement
        assert f"{table_name}.{index_name} ASC" in statement
        assert f"{table_name}.id ASC" in statement
