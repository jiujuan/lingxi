import re
from math import sqrt
from typing import Any

from sqlalchemy import bindparam, cast, exists, func, literal_column, or_, select
from sqlalchemy.orm import Session, aliased

from server.app.core.permissions import AccessContext
from server.app.db.types import PgVector
from server.app.models.document import Document, DocumentStatus
from server.app.models.qa_pair import DocumentChunk, QaPair
from server.app.repositories.document_repo import DocumentRepository
from server.app.schemas.retrieval import RetrievalAccessScope

# tsquery lexemes: keep CJK plus alphanumerics, drop anything that could break
# ``to_tsquery`` parsing (operators, punctuation).
_TS_TOKEN_RE = re.compile(r"[\w一-鿿]+", re.UNICODE)

RankedQaPair = tuple[QaPair, float]
RankedDocumentChunk = tuple[DocumentChunk, float]


class RetrievalRepository:
    """Database-first QA and raw-child retrieval under one access boundary.

    PostgreSQL performs vector/FTS ranking after tenant, ACL, classification,
    document, and source-chunk filters have been applied. SQLite keeps the same
    database scope then ranks the scoped candidates in Python for hermetic tests.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.document_repo = DocumentRepository(session)

    @property
    def _is_postgres(self) -> bool:
        return self.session.get_bind().dialect.name == "postgresql"

    # -- Compatibility API -----------------------------------------------------

    def list_authorized_candidates(
        self,
        context: AccessContext,
        access_scope: RetrievalAccessScope | None = None,
    ) -> list[QaPair]:
        """Legacy QA-only candidate API."""
        return self.list_authorized_qa_candidates(context, access_scope)

    def vector_search(
        self,
        context: AccessContext,
        query_vector: list[float],
        top_k: int,
        access_scope: RetrievalAccessScope | None = None,
    ) -> list[RankedQaPair]:
        """Legacy QA-vector API."""
        return self.search_qa_vector(context, query_vector, top_k, access_scope)

    def text_search(
        self,
        context: AccessContext,
        query_tokens: list[str],
        query_text: str,
        top_k: int,
        access_scope: RetrievalAccessScope | None = None,
    ) -> list[RankedQaPair]:
        """Legacy QA-text API."""
        return self.search_qa_text(
            context, query_tokens, query_text, top_k, access_scope
        )

    # -- Explicit QA and raw-child channels -----------------------------------

    def list_authorized_qa_candidates(
        self,
        context: AccessContext,
        access_scope: RetrievalAccessScope | None = None,
    ) -> list[QaPair]:
        statement = (
            select(QaPair)
            .join(Document, Document.id == QaPair.document_id)
            .where(*self._qa_filters(context, access_scope))
            .order_by(QaPair.document_id, QaPair.pair_index)
        )
        return list(self.session.scalars(statement).unique().all())

    def list_authorized_chunk_candidates(
        self,
        context: AccessContext,
        access_scope: RetrievalAccessScope | None = None,
    ) -> list[DocumentChunk]:
        statement = (
            select(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(*self._chunk_filters(context, access_scope))
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
        )
        return list(self.session.scalars(statement).unique().all())

    def search_qa_vector(
        self,
        context: AccessContext,
        query_vector: list[float],
        top_k: int,
        access_scope: RetrievalAccessScope | None = None,
    ) -> list[RankedQaPair]:
        if not query_vector:
            return []
        filters = self._qa_filters(context, access_scope)
        if self._is_postgres:
            return self._vector_search_pg(
                QaPair, QaPair.question_embedding, filters, query_vector, top_k
            )
        return self._vector_search_python(
            self.list_authorized_qa_candidates(context, access_scope),
            "question_embedding",
            query_vector,
            top_k,
        )

    def search_qa_text(
        self,
        context: AccessContext,
        query_tokens: list[str],
        query_text: str,
        top_k: int,
        access_scope: RetrievalAccessScope | None = None,
    ) -> list[RankedQaPair]:
        filters = self._qa_filters(context, access_scope)
        if self._is_postgres:
            return self._text_search_pg(QaPair, filters, query_tokens, top_k)
        return self._text_search_python(
            self.list_authorized_qa_candidates(context, access_scope),
            query_text,
            top_k,
            fallback_attribute="question",
        )

    def search_chunk_vector(
        self,
        context: AccessContext,
        query_vector: list[float],
        top_k: int,
        access_scope: RetrievalAccessScope | None = None,
    ) -> list[RankedDocumentChunk]:
        if not query_vector:
            return []
        filters = self._chunk_filters(context, access_scope)
        if self._is_postgres:
            return self._vector_search_pg(
                DocumentChunk, DocumentChunk.embedding, filters, query_vector, top_k
            )
        return self._vector_search_python(
            self.list_authorized_chunk_candidates(context, access_scope),
            "embedding",
            query_vector,
            top_k,
        )

    def search_chunk_text(
        self,
        context: AccessContext,
        query_tokens: list[str],
        query_text: str,
        top_k: int,
        access_scope: RetrievalAccessScope | None = None,
    ) -> list[RankedDocumentChunk]:
        filters = self._chunk_filters(context, access_scope)
        if self._is_postgres:
            return self._text_search_pg(DocumentChunk, filters, query_tokens, top_k)
        return self._text_search_python(
            self.list_authorized_chunk_candidates(context, access_scope),
            query_text,
            top_k,
            fallback_attribute="content",
        )

    # -- Shared DB-first access scope -----------------------------------------

    def _qa_filters(
        self, context: AccessContext, access_scope: RetrievalAccessScope | None
    ) -> list:
        return [
            *self._access_scope_filters(context, access_scope, QaPair),
            QaPair.status == "ACTIVE",
            self._qa_source_chunk_is_valid(),
        ]

    def _chunk_filters(
        self, context: AccessContext, access_scope: RetrievalAccessScope | None
    ) -> list:
        return [
            *self._access_scope_filters(context, access_scope, DocumentChunk),
            DocumentChunk.status == "ACTIVE",
            DocumentChunk.chunk_level == "CHILD",
            self._source_parent_is_valid(),
        ]

    def _access_scope_filters(
        self,
        context: AccessContext,
        access_scope: RetrievalAccessScope | None,
        resource: type[QaPair] | type[DocumentChunk],
    ) -> list:
        """Return the tenant/ACL/classification boundary for either channel.

        The caller joins ``Document`` before applying these predicates, making
        the authorization boundary part of each SQL Top-K query rather than a
        post-filter on ranked results.
        """
        return [
            *self._base_access_filters(context, access_scope, resource),
            *self._build_classification_filters(access_scope),
        ]

    def _base_access_filters(
        self,
        context: AccessContext,
        access_scope: RetrievalAccessScope | None,
        resource: type[QaPair] | type[DocumentChunk],
    ) -> list:
        filters: list = [
            Document.tenant_id == context.tenant_id,
            resource.tenant_id == context.tenant_id,
            Document.status == DocumentStatus.READY,
            Document.deleted_at.is_(None),
            resource.deleted_at.is_(None),
        ]
        if not self.document_repo._is_system_admin(context):
            filters.append(self.document_repo._access_exists(context))
        if access_scope and access_scope.document_ids is not None:
            filters.append(resource.document_id.in_(access_scope.document_ids))
        return filters

    # Private compatibility helpers are retained for callers/tests which used
    # the previous QA-only repository surface.
    def _filters(
        self, context: AccessContext, access_scope: RetrievalAccessScope | None
    ) -> list:
        return [
            *self._base_access_filters(context, access_scope, QaPair),
            QaPair.status == "ACTIVE",
            *self._build_classification_filters(access_scope),
        ]

    def _build_document_access_filters(
        self, context: AccessContext, access_scope: RetrievalAccessScope | None
    ) -> list:
        return [
            *self._base_access_filters(context, access_scope, QaPair),
            QaPair.status == "ACTIVE",
        ]

    @staticmethod
    def _build_classification_filters(
        access_scope: RetrievalAccessScope | None,
    ) -> list:
        if access_scope is None:
            return []
        filters = []
        if access_scope.space_id:
            filters.append(Document.knowledge_space_id == access_scope.space_id)
        if access_scope.classification_department_id:
            filters.append(
                Document.category_department_id
                == access_scope.classification_department_id
            )
        if access_scope.category_id:
            filters.append(Document.knowledge_category_id == access_scope.category_id)
        return filters

    @staticmethod
    def _qa_source_chunk_is_valid():
        """Validate the source child/parent for provenance-bearing QA rows.

        Older QA rows may legitimately predate ``chunk_id``. They retain the
        QA-only compatibility path, while any QA that declares a source chunk
        must reference the same live ACTIVE CHILD and, where present, a live
        ACTIVE PARENT.
        """
        child = aliased(DocumentChunk)
        parent = aliased(DocumentChunk)
        valid_parent = exists(
            select(1).where(
                parent.id == child.parent_chunk_id,
                parent.tenant_id == child.tenant_id,
                parent.document_id == child.document_id,
                parent.chunk_level == "PARENT",
                parent.status == "ACTIVE",
                parent.deleted_at.is_(None),
            )
        )
        valid_child = exists(
            select(1).where(
                child.id == QaPair.chunk_id,
                child.tenant_id == QaPair.tenant_id,
                child.document_id == QaPair.document_id,
                child.chunk_level == "CHILD",
                child.status == "ACTIVE",
                child.deleted_at.is_(None),
                or_(child.parent_chunk_id.is_(None), valid_parent),
            )
        )
        return or_(QaPair.chunk_id.is_(None), valid_child)

    @staticmethod
    def _source_parent_is_valid():
        """Require an existing live parent when a child declares one.

        Legacy parser rows predate hierarchical parents and deliberately have a
        NULL ``parent_chunk_id``; they remain valid children. Any non-NULL parent
        reference must resolve to an ACTIVE, non-deleted PARENT of the same
        tenant/document to prevent stale or cross-document provenance leakage.
        """
        parent = aliased(DocumentChunk)
        valid_parent = exists(
            select(1).where(
                parent.id == DocumentChunk.parent_chunk_id,
                parent.tenant_id == DocumentChunk.tenant_id,
                parent.document_id == DocumentChunk.document_id,
                parent.chunk_level == "PARENT",
                parent.status == "ACTIVE",
                parent.deleted_at.is_(None),
            )
        )
        return or_(DocumentChunk.parent_chunk_id.is_(None), valid_parent)

    # -- PostgreSQL: real pgvector / generated tsvector retrieval -------------

    def _vector_search_pg(
        self,
        entity: type[QaPair] | type[DocumentChunk],
        embedding_column: Any,
        filters: list,
        query_vector: list[float],
        top_k: int,
    ) -> list:
        literal = "[" + ",".join(f"{value:.8f}" for value in query_vector) + "]"
        query_expr = cast(bindparam("qvec", literal), PgVector(len(query_vector)))
        distance = embedding_column.op("<=>")(query_expr)
        statement = (
            select(entity, distance.label("distance"))
            .join(Document, Document.id == entity.document_id)
            .where(*filters, embedding_column.isnot(None))
            .order_by(distance.asc(), *self._deterministic_order_columns(entity))
            .limit(top_k)
        )
        rows = self.session.execute(statement).all()
        # pgvector cosine distance -> cosine similarity for comparable scores.
        return [(row[0], 1.0 - float(row[1])) for row in rows]

    def _text_search_pg(
        self,
        entity: type[QaPair] | type[DocumentChunk],
        filters: list,
        query_tokens: list[str],
        top_k: int,
    ) -> list:
        tsquery = self._build_tsquery(query_tokens)
        if not tsquery:
            return []
        # Both tables expose a generated ``search_vector`` plus a partial GIN
        # index. Referencing the stored column preserves that index path.
        search_vector = literal_column(f"{entity.__tablename__}.search_vector")
        query_expr = func.to_tsquery("simple", bindparam("tsq", tsquery))
        rank = func.ts_rank(search_vector, query_expr)
        statement = (
            select(entity, rank.label("rank"))
            .join(Document, Document.id == entity.document_id)
            .where(*filters, search_vector.op("@@")(query_expr))
            .order_by(rank.desc(), *self._deterministic_order_columns(entity))
            .limit(top_k)
        )
        rows = self.session.execute(statement).all()
        return [(row[0], float(row[1])) for row in rows]

    @staticmethod
    def _build_tsquery(tokens: list[str]) -> str:
        lexemes: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            for match in _TS_TOKEN_RE.findall(token.lower()):
                if match not in seen:
                    seen.add(match)
                    lexemes.append(match)
        return " | ".join(lexemes)

    # -- SQLite / non-PostgreSQL fallback -------------------------------------

    def _vector_search_python(
        self,
        candidates: list[QaPair] | list[DocumentChunk],
        embedding_attribute: str,
        query_vector: list[float],
        top_k: int,
    ) -> list:
        # Candidates have already been scoped by the DB query above; sorting only
        # happens after tenant/ACL/classification/deletion predicates are applied.
        ranked = [
            (item, self._cosine(query_vector, getattr(item, embedding_attribute) or []))
            for item in candidates
            if getattr(item, embedding_attribute)
        ]
        ranked.sort(
            key=lambda row: (-row[1], *self._deterministic_ranking_key(row[0]))
        )
        return ranked[:top_k]

    def _text_search_python(
        self,
        candidates: list[QaPair] | list[DocumentChunk],
        query_text: str,
        top_k: int,
        *,
        fallback_attribute: str,
    ) -> list:
        ranked = [
            (
                item,
                self._char_overlap(
                    query_text,
                    item.search_text or getattr(item, fallback_attribute),
                ),
            )
            for item in candidates
        ]
        # PostgreSQL's ``@@`` only returns matches. Keep the SQLite fallback
        # equivalent rather than allowing zero-score scoped rows into Top-K.
        ranked = [row for row in ranked if row[1] > 0]
        ranked.sort(
            key=lambda row: (-row[1], *self._deterministic_ranking_key(row[0]))
        )
        return ranked[:top_k]

    @staticmethod
    def _deterministic_order_columns(
        entity: type[QaPair] | type[DocumentChunk],
    ) -> tuple:
        index_column = (
            QaPair.pair_index if entity is QaPair else DocumentChunk.chunk_index
        )
        return (entity.document_id.asc(), index_column.asc(), entity.id.asc())

    @staticmethod
    def _deterministic_ranking_key(
        item: QaPair | DocumentChunk,
    ) -> tuple[str, int, str]:
        index = getattr(item, "pair_index", getattr(item, "chunk_index", 0))
        return (str(item.document_id), int(index), str(item.id))

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = sqrt(sum(a * a for a in left))
        right_norm = sqrt(sum(b * b for b in right))
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)

    @staticmethod
    def _char_overlap(query: str, search_text: str) -> float:
        query_terms = {char for char in query.lower() if not char.isspace()}
        doc_terms = {char for char in search_text.lower() if not char.isspace()}
        if not query_terms:
            return 0.0
        return len(query_terms & doc_terms) / len(query_terms)
