import re
from math import sqrt

from sqlalchemy import bindparam, cast, func, literal_column, select
from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext
from server.app.db.types import PgVector
from server.app.models.document import Document
from server.app.models.qa_pair import QaPair
from server.app.repositories.document_repo import DocumentRepository
from server.app.schemas.retrieval import RetrievalAccessScope

# tsquery lexemes: keep CJK plus alphanumerics, drop anything that could break
# ``to_tsquery`` parsing (operators, punctuation).
_TS_TOKEN_RE = re.compile(r"[\w一-鿿]+", re.UNICODE)

RankedQaPair = tuple[QaPair, float]


class RetrievalRepository:
    """Candidate retrieval with the scoring pushed to the database on
    PostgreSQL (pgvector ``<=>`` + tsvector ``ts_rank``) and an in-Python
    fallback on other dialects (SQLite) so the test suite stays hermetic.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.document_repo = DocumentRepository(session)

    @property
    def _is_postgres(self) -> bool:
        return self.session.get_bind().dialect.name == "postgresql"

    def list_authorized_candidates(
        self,
        context: AccessContext,
        access_scope: RetrievalAccessScope | None = None,
    ) -> list[QaPair]:
        candidates = self.document_repo.list_authorized_qa_pairs(context)
        if access_scope and access_scope.document_ids is not None:
            candidates = [
                item for item in candidates if item.document_id in access_scope.document_ids
            ]
        return candidates

    def vector_search(
        self,
        context: AccessContext,
        query_vector: list[float],
        top_k: int,
        access_scope: RetrievalAccessScope | None = None,
    ) -> list[RankedQaPair]:
        if not query_vector:
            return []
        if self._is_postgres:
            return self._vector_search_pg(context, query_vector, top_k, access_scope)
        return self._vector_search_python(context, query_vector, top_k, access_scope)

    def text_search(
        self,
        context: AccessContext,
        query_tokens: list[str],
        query_text: str,
        top_k: int,
        access_scope: RetrievalAccessScope | None = None,
    ) -> list[RankedQaPair]:
        if self._is_postgres:
            return self._text_search_pg(context, query_tokens, top_k, access_scope)
        return self._text_search_python(context, query_text, top_k, access_scope)

    # -- PostgreSQL: real index-backed retrieval -------------------------------

    def _vector_search_pg(
        self,
        context: AccessContext,
        query_vector: list[float],
        top_k: int,
        access_scope: RetrievalAccessScope | None,
    ) -> list[RankedQaPair]:
        literal = "[" + ",".join(f"{value:.8f}" for value in query_vector) + "]"
        query_expr = cast(bindparam("qvec", literal), PgVector(len(query_vector)))
        distance = QaPair.question_embedding.op("<=>")(query_expr)
        statement = (
            select(QaPair, distance.label("distance"))
            .join(Document, Document.id == QaPair.document_id)
            .where(
                *self._filters(context, access_scope),
                QaPair.question_embedding.isnot(None),
            )
            .order_by(distance.asc())
            .limit(top_k)
        )
        rows = self.session.execute(statement).all()
        # pgvector cosine distance -> cosine similarity for a comparable score.
        return [(row[0], 1.0 - float(row[1])) for row in rows]

    def _text_search_pg(
        self,
        context: AccessContext,
        query_tokens: list[str],
        top_k: int,
        access_scope: RetrievalAccessScope | None,
    ) -> list[RankedQaPair]:
        tsquery = self._build_tsquery(query_tokens)
        if not tsquery:
            return []
        # Match against the stored generated ``search_vector`` column so the GIN
        # index is used; recomputing to_tsvector inline would bypass it.
        search_vector = literal_column("search_vector")
        query_expr = func.to_tsquery("simple", bindparam("tsq", tsquery))
        rank = func.ts_rank(search_vector, query_expr)
        statement = (
            select(QaPair, rank.label("rank"))
            .join(Document, Document.id == QaPair.document_id)
            .where(
                *self._filters(context, access_scope),
                search_vector.op("@@")(query_expr),
            )
            .order_by(rank.desc())
            .limit(top_k)
        )
        rows = self.session.execute(statement).all()
        return [(row[0], float(row[1])) for row in rows]

    def _filters(
        self, context: AccessContext, access_scope: RetrievalAccessScope | None
    ) -> list:
        filters = self.document_repo.authorized_qa_filters(context)
        if access_scope and access_scope.document_ids is not None:
            filters.append(QaPair.document_id.in_(access_scope.document_ids))
        return filters

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

    # -- Fallback: in-Python scoring (SQLite / tests) --------------------------

    def _vector_search_python(
        self,
        context: AccessContext,
        query_vector: list[float],
        top_k: int,
        access_scope: RetrievalAccessScope | None,
    ) -> list[RankedQaPair]:
        candidates = self.list_authorized_candidates(context, access_scope)
        ranked = [
            (item, self._cosine(query_vector, item.question_embedding or []))
            for item in candidates
            if item.question_embedding
        ]
        ranked.sort(key=lambda row: row[1], reverse=True)
        return ranked[:top_k]

    def _text_search_python(
        self,
        context: AccessContext,
        query_text: str,
        top_k: int,
        access_scope: RetrievalAccessScope | None,
    ) -> list[RankedQaPair]:
        candidates = self.list_authorized_candidates(context, access_scope)
        ranked = [
            (item, self._char_overlap(query_text, item.search_text or item.question))
            for item in candidates
        ]
        ranked.sort(key=lambda row: row[1], reverse=True)
        return ranked[:top_k]

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
