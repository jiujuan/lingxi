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
