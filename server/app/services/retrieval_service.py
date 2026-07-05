from math import sqrt
from time import perf_counter

from sqlalchemy.orm import Session

from server.app.core.ids import current_request_id
from server.app.core.permissions import AccessContext
from server.app.core.retrieval_config import RetrievalConfig, get_retrieval_config
from server.app.integrations.model_providers.registry import build_provider_adapter
from server.app.repositories.missed_question_repo import MissedQuestionRepository
from server.app.repositories.retrieval_repo import RetrievalRepository
from server.app.schemas.retrieval import (
    RetrievalAccessScope,
    RetrievalCandidate,
    RetrievalResult,
)
from server.app.services.embedding_service import EmbeddingService
from server.app.services.rerank_service import RerankService


class RetrievalService:
    def __init__(
        self,
        session: Session,
        config: RetrievalConfig | None = None,
        reranker: RerankService | None = None,
    ) -> None:
        self.session = session
        self.config = config or get_retrieval_config()
        self.repo = RetrievalRepository(session)
        self.reranker = reranker or RerankService()

    def retrieve(
        self,
        context: AccessContext,
        question: str,
        access_scope: RetrievalAccessScope | None = None,
    ) -> RetrievalResult:
        started = perf_counter()
        query_vector = self._embed_query(context.tenant_id, question)
        qa_pairs = self.repo.list_authorized_candidates(context, access_scope=access_scope)

        vector_ranked = sorted(
            [
                (
                    item,
                    self._cosine(query_vector, item.question_embedding or []),
                )
                for item in qa_pairs
                if item.question_embedding
            ],
            key=lambda row: row[1],
            reverse=True,
        )[: self.config.vector_top_k]
        text_ranked = [
            (item, self._text_score(question, item.search_text or item.question))
            for item in qa_pairs
        ]
        text_ranked = sorted(text_ranked, key=lambda row: row[1], reverse=True)[
            : self.config.text_top_k
        ]

        fused = self._rrf(vector_ranked, text_ranked)
        reranked = self.reranker.rerank(question, fused)[: self.config.final_top_k]
        confidence = reranked[0].rerank_score if reranked else 0.0
        has_answer = bool(reranked and confidence >= self.config.low_confidence_threshold)

        snapshot = {
            "question": question,
            "stages": {
                "vector": [self._rank_snapshot(item, score) for item, score in vector_ranked],
                "text": [self._rank_snapshot(item, score) for item, score in text_ranked],
                "rrf": [item.to_snapshot() for item in fused],
                "rerank": [item.to_snapshot() for item in reranked],
            },
            "filters": {
                "authorizedCandidates": len(qa_pairs),
                "scopeDocumentIds": sorted(access_scope.document_ids)
                if access_scope and access_scope.document_ids
                else None,
            },
            "latencyMs": int((perf_counter() - started) * 1000),
            "requestId": current_request_id(),
        }
        result = RetrievalResult(
            question=question,
            candidates=reranked,
            has_answer=has_answer,
            confidence=confidence,
            snapshot=snapshot,
        )
        if not has_answer:
            MissedQuestionRepository(self.session).record(
                context.tenant_id,
                question,
                {
                    "requestId": current_request_id(),
                    "confidence": round(confidence, 6),
                    "candidateCount": len(reranked),
                },
            )
            self.session.commit()
        return result

    def _embed_query(self, tenant_id: str, question: str) -> list[float]:
        try:
            model_config, provider = EmbeddingService(self.session)._default_model(tenant_id)
            adapter = build_provider_adapter(
                provider.provider_type,
                provider.base_url,
                None,
                {**(provider.config or {}), **(model_config.config or {})},
            )
            return adapter.embed_texts([question])[0]
        except Exception:
            return self._fallback_embedding(question, 4)

    def _rrf(
        self,
        vector_ranked,
        text_ranked,
    ) -> list[RetrievalCandidate]:
        by_id: dict[str, RetrievalCandidate] = {}
        vector_scores = {item.id: score for item, score in vector_ranked}
        text_scores = {item.id: score for item, score in text_ranked}

        for ranked in (vector_ranked, text_ranked):
            for rank, (qa_pair, _score) in enumerate(ranked, start=1):
                candidate = by_id.get(qa_pair.id)
                if candidate is None:
                    candidate = RetrievalCandidate(
                        qa_pair_id=qa_pair.id,
                        document_id=qa_pair.document_id,
                        question=qa_pair.question,
                        answer=qa_pair.answer,
                        quote=qa_pair.quote,
                        page_no=qa_pair.page_no,
                        pair_index=qa_pair.pair_index,
                    )
                    by_id[qa_pair.id] = candidate
                candidate.rrf_score += 1 / (self.config.rrf_k + rank)
                candidate.source_rank = rank

        for candidate in by_id.values():
            candidate.vector_score = vector_scores.get(candidate.qa_pair_id, 0.0)
            candidate.text_score = text_scores.get(candidate.qa_pair_id, 0.0)
        return sorted(by_id.values(), key=lambda item: item.rrf_score, reverse=True)

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
    def _text_score(query: str, search_text: str) -> float:
        query_terms = {char for char in query.lower() if not char.isspace()}
        doc_terms = {char for char in search_text.lower() if not char.isspace()}
        if not query_terms:
            return 0.0
        return len(query_terms & doc_terms) / len(query_terms)

    @staticmethod
    def _fallback_embedding(text: str, dimension: int) -> list[float]:
        values = [float((ord(char) % 29) + 1) for char in text[:dimension]]
        values.extend([0.0] * (dimension - len(values)))
        return values[:dimension]

    @staticmethod
    def _rank_snapshot(qa_pair, score: float) -> dict:
        return {
            "qaPairId": qa_pair.id,
            "documentId": qa_pair.document_id,
            "question": qa_pair.question,
            "score": round(score, 6),
        }
