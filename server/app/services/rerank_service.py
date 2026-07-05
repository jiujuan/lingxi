from server.app.schemas.retrieval import RetrievalCandidate


class RerankService:
    def rerank(
        self, query: str, candidates: list[RetrievalCandidate]
    ) -> list[RetrievalCandidate]:
        query_norm = self._normalize(query)
        for candidate in candidates:
            question_norm = self._normalize(candidate.question)
            exact_boost = 1.0 if query_norm and query_norm in question_norm else 0.0
            title_overlap = self._overlap(query_norm, question_norm)
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
    def _normalize(value: str) -> str:
        return "".join(value.lower().split())

    @staticmethod
    def _overlap(left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        left_chars = set(left)
        right_chars = set(right)
        return len(left_chars & right_chars) / max(len(left_chars), 1)
