from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import event

from server.app.core.permissions import AccessContext
from server.app.models.document import (
    Document,
    DocumentAccessRule,
    DocumentAccessSubjectType,
    DocumentStatus,
)
from server.app.models.qa_pair import DocumentChunk
from server.app.schemas.retrieval import RetrievalAccessScope, RetrievalCandidate
from server.app.services.context_hydration_service import ContextHydrationService
from server.tests.test_document_permissions import build_session


@dataclass(frozen=True)
class WordTokenCounter:
    name: str = "word-fixture"
    version: str = "1.0"

    def count(self, text: str) -> int:
        return len(text.split())

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        words = text.split()
        return [
            " ".join(words[index : index + limit])
            for index in range(0, len(words), limit)
        ]


def _context(identity) -> AccessContext:
    employee = identity["users"]["employee"]
    employee_role = identity["roles"]["employee"]
    support = identity["departments"]["support"]
    return AccessContext(
        tenant_id=identity["tenant"].id,
        user_id=employee.id,
        department_id=support.id,
        department_ids=[support.id],
        role_ids=[employee_role.id],
        permissions={"DOCUMENT_READ"},
    )


def _candidate(chunk: DocumentChunk, score: float) -> RetrievalCandidate:
    return RetrievalCandidate(
        qa_pair_id=None,
        document_id=chunk.document_id,
        question="退款审批",
        answer=chunk.content,
        quote="精准 Child 引用",
        page_no=chunk.page_start,
        pair_index=chunk.chunk_index,
        evidence_id=chunk.id,
        evidence_type="CHUNK",
        chunk_id=chunk.id,
        parent_chunk_id=chunk.parent_chunk_id,
        content=chunk.content,
        title_path=tuple(chunk.title_path),
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        source_locator=chunk.source_locator,
        fused_score=score,
    )


def _seed_hierarchy(session, identity):
    tenant_id = identity["tenant"].id
    document = Document(
        tenant_id=tenant_id,
        title="退款流程",
        file_name="refund.md",
        file_type="MARKDOWN",
        mime_type="text/markdown",
        file_size=100,
        object_key="documents/refund.md",
        checksum="hydration-refund",
        status=DocumentStatus.READY,
    )
    session.add(document)
    session.flush()
    session.add(
        DocumentAccessRule(
            tenant_id=tenant_id,
            document_id=document.id,
            subject_type=DocumentAccessSubjectType.ALL_AUTHENTICATED,
            subject_id=None,
        )
    )
    parent = DocumentChunk(
        tenant_id=tenant_id,
        document_id=document.id,
        chunk_index=100,
        title_path=["退款", "审批"],
        content=(
            "BEGIN 不应从父块开头机械截取 zero one two three four five six seven "
            "命中 Child 精确内容 before-after 补充上下文 nine ten eleven twelve END"
        ),
        status="ACTIVE",
        chunk_level="PARENT",
    )
    session.add(parent)
    session.flush()
    children = []
    for index, content in enumerate(
        ["前序 邻居", "命中 Child 精确内容", "后序 邻居"], start=1
    ):
        child = DocumentChunk(
            tenant_id=tenant_id,
            document_id=document.id,
            chunk_index=index,
            title_path=["退款", "审批"],
            content=content,
            page_start=1,
            page_end=1,
            source_locator={"block": index},
            status="ACTIVE",
            chunk_level="CHILD",
            parent_chunk_id=parent.id,
        )
        session.add(child)
        children.append(child)
    session.commit()
    return parent, children


def test_hydration_reloads_scoped_parent_and_neighbors_without_repeating_child_overlap():
    session, identity = build_session()
    parent, children = _seed_hierarchy(session, identity)

    hydrated = ContextHydrationService(
        session,
        token_counter=WordTokenCounter(),
        neighbor_window=1,
        parent_max_tokens_per_hit=8,
    ).hydrate(_context(identity), [_candidate(children[1], 0.9)])

    segments = hydrated[0]._lingxi_context_segments
    assert [item.kind for item in segments] == ["PARENT", "NEIGHBOR", "NEIGHBOR"]
    assert all("命中 Child 精确内容" not in item.content for item in segments)
    assert any("补充上下文" in item.content for item in segments)
    assert all("BEGIN" not in item.content for item in segments if item.kind == "PARENT")
    assert {item.context_chunk_id for item in segments if item.kind == "NEIGHBOR"} == {
        children[0].id,
        children[2].id,
    }
    assert all(item.parent_chunk_id == parent.id for item in segments)


def test_hydration_applies_current_access_scope_instead_of_loading_parent_by_id():
    session, identity = build_session()
    parent, children = _seed_hierarchy(session, identity)
    # Revoking the document grant after retrieval must also revoke hydration.
    session.delete(session.scalar(
        __import__("sqlalchemy").select(DocumentAccessRule).where(
            DocumentAccessRule.document_id == children[1].document_id
        )
    ))
    session.commit()

    hydrated = ContextHydrationService(session, token_counter=WordTokenCounter()).hydrate(
        _context(identity), [_candidate(children[1], 0.9)]
    )

    assert hydrated[0]._lingxi_context_segments == ()


def test_hydration_uses_current_child_parent_relation_not_untrusted_candidate_parent_id():
    session, identity = build_session()
    _parent, children = _seed_hierarchy(session, identity)
    candidate = _candidate(children[1], 0.9)
    candidate.parent_chunk_id = "not-a-scoped-parent"

    hydrated = ContextHydrationService(session, token_counter=WordTokenCounter()).hydrate(
        _context(identity), [candidate]
    )

    assert hydrated[0]._lingxi_context_segments
    assert all(item.parent_chunk_id == children[1].parent_chunk_id for item in hydrated[0]._lingxi_context_segments)



def test_retrieval_hydration_failure_keeps_the_winning_child_for_prompt_and_citation(monkeypatch):
    from dataclasses import replace

    from server.app.core.retrieval_config import get_retrieval_config
    from server.app.services.retrieval_service import RetrievalService

    class BrokenHydrator:
        def hydrate(self, *_args, **_kwargs):
            raise RuntimeError("hydration store unavailable")

    session, identity = build_session()
    _parent, children = _seed_hierarchy(session, identity)
    child_candidate = _candidate(children[1], 0.9)
    service = RetrievalService(
        session,
        config=replace(get_retrieval_config(), final_top_k=1),
        hybrid_chunk_retrieval_enabled=True,
        parent_context_enabled=True,
        context_hydration_service=BrokenHydrator(),
    )
    monkeypatch.setattr(service, "_embed_query", lambda *_args: [1.0])
    monkeypatch.setattr(service.tokenizer, "tokenize", lambda _question: ["退款"])
    monkeypatch.setattr(
        service,
        "_retrieve_hybrid",
        lambda *_args: (
            [child_candidate],
            {"qa_vector": [], "qa_text": [], "chunk_vector": [], "chunk_text": []},
            False,
        ),
    )

    result = service.retrieve(_context(identity), "退款怎么审批")

    assert result.candidates[0].chunk_id == children[1].id
    assert result.candidates[0].quote == "精准 Child 引用"
    assert result.candidates[0]._lingxi_context_segments == ()



def test_hydration_neighbor_window_is_calculated_for_each_source_child_not_per_parent():
    session, identity = build_session()
    parent, children = _seed_hierarchy(session, identity)
    distant_children = []
    for index, content in [(9, "远处前邻居"), (10, "远处命中 Child"), (11, "远处后邻居")]:
        child = DocumentChunk(
            tenant_id=identity["tenant"].id,
            document_id=children[0].document_id,
            chunk_index=index,
            title_path=["退款", "审批"],
            content=content,
            status="ACTIVE",
            chunk_level="CHILD",
            parent_chunk_id=parent.id,
        )
        session.add(child)
        distant_children.append(child)
    session.commit()

    near_candidate = _candidate(children[1], 0.9)
    distant_candidate = _candidate(distant_children[1], 0.8)
    hydrated = ContextHydrationService(
        session, token_counter=WordTokenCounter(), neighbor_window=1
    ).hydrate(_context(identity), [near_candidate, distant_candidate])

    near_neighbor_ids = {
        item.context_chunk_id
        for item in hydrated[0]._lingxi_context_segments
        if item.kind == "NEIGHBOR"
    }
    distant_neighbor_ids = {
        item.context_chunk_id
        for item in hydrated[1]._lingxi_context_segments
        if item.kind == "NEIGHBOR"
    }
    assert near_neighbor_ids == {children[0].id, children[2].id}
    assert distant_neighbor_ids == {distant_children[0].id, distant_children[2].id}


def test_hydration_pushes_each_neighbor_window_into_the_sql_query():
    session, identity = build_session()
    parent, children = _seed_hierarchy(session, identity)
    distant_children = []
    for index, content in [(9, "远处前邻居"), (10, "远处命中 Child"), (11, "远处后邻居")]:
        child = DocumentChunk(
            tenant_id=identity["tenant"].id,
            document_id=children[0].document_id,
            chunk_index=index,
            title_path=["退款", "审批"],
            content=content,
            status="ACTIVE",
            chunk_level="CHILD",
            parent_chunk_id=parent.id,
        )
        session.add(child)
        distant_children.append(child)
    for index in range(100, 130):
        session.add(
            DocumentChunk(
                tenant_id=identity["tenant"].id,
                document_id=children[0].document_id,
                chunk_index=index,
                title_path=["退款", "审批"],
                content=f"不应由邻居查询 materialize 的远端块 {index}",
                status="ACTIVE",
                chunk_level="CHILD",
                parent_chunk_id=parent.id,
            )
        )
    session.commit()

    statements: list[str] = []

    def record_neighbor_query(_conn, _cursor, statement, _parameters, _context, _many):
        if (
            "ORDER BY document_chunks.parent_chunk_id" in statement
            and "document_chunks.chunk_level" in statement
        ):
            statements.append(statement)

    event.listen(session.bind, "before_cursor_execute", record_neighbor_query)
    try:
        ContextHydrationService(
            session, token_counter=WordTokenCounter(), neighbor_window=1
        ).hydrate(
            _context(identity),
            [_candidate(children[1], 0.9), _candidate(distant_children[1], 0.8)],
        )
    finally:
        event.remove(session.bind, "before_cursor_execute", record_neighbor_query)

    assert len(statements) == 1
    neighbor_sql = statements[0]
    assert "document_chunks.parent_chunk_id = ?" in neighbor_sql
    assert "document_chunks.document_id = ?" in neighbor_sql
    assert "document_chunks.chunk_index >= ?" in neighbor_sql
    assert "document_chunks.chunk_index <= ?" in neighbor_sql
    assert " OR " in neighbor_sql


def test_hydration_centers_a_token_safe_parent_window_when_child_crosses_split_boundary():
    session, identity = build_session()
    parent, children = _seed_hierarchy(session, identity)
    children[1].content = "boundary-a boundary-b"
    parent.content = (
        "BEGIN zero one two boundary-a boundary-b nearby-context "
        "tail-one tail-two tail-three END"
    )
    session.commit()

    hydrated = ContextHydrationService(
        session, token_counter=WordTokenCounter(), parent_max_tokens_per_hit=5
    ).hydrate(_context(identity), [_candidate(children[1], 0.9)])

    parent_segments = [
        item.content
        for item in hydrated[0]._lingxi_context_segments
        if item.kind == "PARENT"
    ]
    assert parent_segments
    assert all("BEGIN" not in item for item in parent_segments)
    assert any("nearby-context" in item for item in parent_segments)
    assert all(WordTokenCounter().count(item) <= 5 for item in parent_segments)


def test_hydration_excludes_deleted_parent_and_classification_out_of_scope_context():
    session, identity = build_session()
    parent, children = _seed_hierarchy(session, identity)

    classification_out_of_scope = ContextHydrationService(
        session, token_counter=WordTokenCounter()
    ).hydrate(
        _context(identity),
        [_candidate(children[1], 0.9)],
        RetrievalAccessScope(space_id="not-authorized-space"),
    )
    assert classification_out_of_scope[0]._lingxi_context_segments == ()

    parent.status = "DELETED"
    session.commit()
    deleted_parent = ContextHydrationService(
        session, token_counter=WordTokenCounter()
    ).hydrate(_context(identity), [_candidate(children[1], 0.9)])
    assert deleted_parent[0]._lingxi_context_segments == ()


def test_hydration_removes_whitespace_variant_child_overlap_from_parent_context():
    session, identity = build_session()
    parent, children = _seed_hierarchy(session, identity)
    parent.content = "前文 命中   Child  精确内容 后文增量信息"
    session.commit()

    hydrated = ContextHydrationService(session, token_counter=WordTokenCounter()).hydrate(
        _context(identity), [_candidate(children[1], 0.9)]
    )

    parent_text = next(
        item.content
        for item in hydrated[0]._lingxi_context_segments
        if item.kind == "PARENT"
    )
    assert "命中 Child 精确内容" not in parent_text
    assert "后文增量信息" in parent_text
