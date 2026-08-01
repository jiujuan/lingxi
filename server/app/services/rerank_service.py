from server.app.schemas.retrieval import RetrievalCandidate


class RerankService:
    def rerank(
        self, query: str, candidates: list[RetrievalCandidate]
    ) -> list[RetrievalCandidate]:
        query_norm = self._normalize(query)
        for candidate in candidates:
            # Keep the legacy QA ranking signal unchanged.  Unified hybrid
            # evidence is chunk-centric, so its candidate representation adds
            # document structure and source content to the rerank input.
            if candidate.evidence_id is None:
                score_text = candidate.question
            else:
                # Keep the complete query/title/content input available for a
                # model-backed reranker, but calculate lexical relevance from
                # the source fields so injecting the query itself cannot make
                # every Chunk an exact match.
                rerank_input = self._hybrid_evidence_text(query, candidate)
                # The lexical fallback intentionally scores the evidence part
                # after the query prefix; otherwise including the query in the
                # complete rerank input would make every Chunk an exact match.
                _query_prefix, _separator, score_text = rerank_input.partition("\n")
            score_text_norm = self._normalize(score_text)
            exact_boost = 1.0 if query_norm and query_norm in score_text_norm else 0.0
            title_overlap = self._overlap(query_norm, score_text_norm)
            position_boost = 1 / (1 + max(candidate.pair_index, 0))
            candidate.rerank_score = (
                candidate.rrf_score * 8
                + candidate.vector_score * 0.35
                + candidate.text_score * 0.45
                + exact_boost * 1.2
                + title_overlap * 0.5
                + position_boost * 0.15
            )
        return sorted(
            candidates,
            key=lambda item: (item.rerank_score, item.rrf_score, item.text_score),
            reverse=True,
        )

    @staticmethod
    def _hybrid_evidence_text(query: str, candidate: RetrievalCandidate) -> str:
        """Build the complete hybrid rerank input from query and Chunk evidence."""
        return "\n".join(
            part
            for part in (
                query,
                " / ".join(candidate.title_path),
                candidate.content or candidate.answer,
            )
            if part
        )

    @staticmethod
    def _normalize(value: str) -> str:
        return "".join(value.lower().split())

    @staticmethod
    def _overlap(left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        left_chars = set(left)
        right_chars = set(right)
        return len(left_chars & right_chars) / max(len(left_chars), 1)
