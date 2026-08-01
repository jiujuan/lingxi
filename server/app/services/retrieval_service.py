import hashlib
import json
import logging
import math
from dataclasses import replace
from time import perf_counter
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.core import metrics
from server.app.core.ids import current_request_id
from server.app.core.log_redaction import sanitize_retrieval_snapshot
from server.app.core.permissions import AccessContext
from server.app.core.retrieval_config import RetrievalConfig, get_retrieval_config
from server.app.core.secrets import decrypt_secret
from server.app.integrations.model_providers.registry import (
    ProviderFactory,
    build_provider_adapter,
)
from server.app.integrations.tokenizers.base import SearchTextTokenizer
from server.app.integrations.tokenizers.jieba_tokenizer import JiebaTokenizer
from server.app.models.qa_pair import DocumentChunk, QaPair
from server.app.repositories.missed_question_repo import MissedQuestionRepository
from server.app.repositories.retrieval_repo import RetrievalRepository
from server.app.schemas.retrieval import (
    RetrievalAccessScope,
    RetrievalCandidate,
    RetrievalEvidence,
    RetrievalResult,
)
from server.app.services.context_hydration_service import ContextHydrationService
from server.app.services.embedding_service import EmbeddingService
from server.app.services.rerank_service import RerankService

logger = logging.getLogger(__name__)


_CHANNEL_NAMES = ("qa_vector", "qa_text", "chunk_vector", "chunk_text")
_DEFAULT_RRF_CHANNEL_WEIGHTS = {channel: 1.0 for channel in _CHANNEL_NAMES}


class ChunkChannelUnavailableError(RuntimeError):
    """A declared operational failure for the optional Chunk channels.

    This is intentionally narrow: permission, validation, and configuration
    failures must keep their original exception semantics instead of silently
    changing a query's access boundary.
    """


class RetrievalService:
    def __init__(
        self,
        session: Session,
        config: RetrievalConfig | None = None,
        reranker: RerankService | None = None,
        tokenizer: SearchTextTokenizer | None = None,
        provider_factory: ProviderFactory = build_provider_adapter,
        *,
        hybrid_chunk_retrieval_enabled: bool = False,
        rrf_channel_weights: Mapping[str, float] | None = None,
        parent_context_enabled: bool = False,
        context_hydration_service: ContextHydrationService | None = None,
    ) -> None:
        self.session = session
        self.config = config or get_retrieval_config()
        self.repo = RetrievalRepository(session)
        self.reranker = reranker or RerankService()
        self.tokenizer = tokenizer or JiebaTokenizer()
        self._build_adapter = provider_factory
        self.hybrid_chunk_retrieval_enabled = hybrid_chunk_retrieval_enabled
        self.rrf_channel_weights = self._normalize_channel_weights(rrf_channel_weights)
        self.parent_context_enabled = parent_context_enabled
        # Keep legacy/QA-only startup independent from the optional hierarchy
        # tokenizer.  The hydration service is created only if this feature is
        # actually enabled (or explicitly injected for tests/DI).
        self.context_hydration_service = context_hydration_service

    def retrieve(
        self,
        context: AccessContext,
        question: str,
        access_scope: RetrievalAccessScope | None = None,
    ) -> RetrievalResult:
        started = perf_counter()
        access_scope = normalize_retrieval_scope(access_scope)
        logger.debug(
            "retrieval classification scope",
            extra={
                "tenant_id": context.tenant_id,
                "request_id": current_request_id(),
                **_scope_log_fields(access_scope),
            },
        )
        query_vector = self._embed_query(context.tenant_id, question)
        query_tokens = self.tokenizer.tokenize(question)
        retrieval_started = perf_counter()
        config_hash = self._observability_config_hash()

        if self.hybrid_chunk_retrieval_enabled:
            fused, stages, chunk_degraded = self._retrieve_hybrid(
                context, question, query_vector, query_tokens, access_scope
            )
            snapshot = self._hybrid_snapshot(
                question,
                stages,
                fused,
                access_scope,
                started,
                chunk_degraded,
                config_hash,
            )
            candidate_counts = {
                channel: len(stages[channel]) for channel in _CHANNEL_NAMES
            }
        else:
            vector_ranked = self.repo.vector_search(
                context, query_vector, self.config.vector_top_k, access_scope
            )
            text_ranked = self.repo.text_search(
                context, query_tokens, question, self.config.text_top_k, access_scope
            )
            fused = self._rrf(vector_ranked, text_ranked)
            snapshot = self._legacy_snapshot(
                question,
                vector_ranked,
                text_ranked,
                fused,
                access_scope,
                started,
                config_hash,
            )
            candidate_counts = {
                "qa_vector": len(vector_ranked),
                "qa_text": len(text_ranked),
            }
            chunk_degraded = False
        retrieve_duration = perf_counter() - retrieval_started

        rerank_started = perf_counter()
        reranked = self.reranker.rerank(question, fused)[: self.config.final_top_k]
        rerank_duration = perf_counter() - rerank_started
        hydration_duration = 0.0
        if self.hybrid_chunk_retrieval_enabled and self.parent_context_enabled:
            hydration_started = perf_counter()
            try:
                hydrator = self.context_hydration_service or ContextHydrationService(
                    self.session
                )
                reranked = hydrator.hydrate(context, reranked, access_scope)
            except Exception:
                # Hydration only enriches a winning Child.  Its failure must
                # never change retrieval/citation identity or turn a usable
                # result into an outage; PromptService will use Child-only.
                logger.exception(
                    "context hydration failed; using child-only evidence",
                    extra={
                        "tenant_id": context.tenant_id,
                        "request_id": current_request_id(),
                    },
                )
                for candidate in reranked:
                    candidate._lingxi_context_segments = ()
            finally:
                hydration_duration = perf_counter() - hydration_started
        confidence = reranked[0].rerank_score if reranked else 0.0
        has_answer = bool(reranked and confidence >= self.config.low_confidence_threshold)
        snapshot["stages"]["rerank"] = [
            item.to_snapshot() for item in reranked
        ][: self.config.snapshot_max_items_per_stage]
        snapshot = sanitize_retrieval_snapshot(
            snapshot,
            max_items_per_stage=self.config.snapshot_max_items_per_stage,
        )
        hydration_tokens = self._hydration_token_count(reranked)
        channel_hit_ratios = {
            channel: 1.0 if count else 0.0
            for channel, count in candidate_counts.items()
        }
        raw_candidate_count = sum(candidate_counts.values())
        dedup_ratio = (
            max(0.0, (raw_candidate_count - len(fused)) / raw_candidate_count)
            if raw_candidate_count
            else 0.0
        )
        metrics.observe_retrieval(
            candidate_counts=candidate_counts,
            channel_hit_ratios=channel_hit_ratios,
            dedup_ratio=dedup_ratio,
            hydration_tokens=hydration_tokens,
            latency_by_stage_seconds={
                "retrieve": retrieve_duration,
                "rerank": rerank_duration,
                "hydrate": hydration_duration,
            },
            degraded_reason=(
                "chunk_channel_unavailable" if chunk_degraded else None
            ),
        )
        logger.info(
            "retrieval completed",
            extra={
                "tenant_id": context.tenant_id,
                "request_id": current_request_id(),
                "config_hash": config_hash,
                "hybrid_chunk_retrieval_enabled": self.hybrid_chunk_retrieval_enabled,
                "parent_context_enabled": self.parent_context_enabled,
                "candidate_counts": candidate_counts,
                "fused_candidate_count": len(fused),
                "final_candidate_count": len(reranked),
                "chunk_retrieval_degraded": chunk_degraded,
                "latency_ms": int((perf_counter() - started) * 1000),
            },
        )
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

    def _retrieve_hybrid(
        self,
        context: AccessContext,
        question: str,
        query_vector: list[float],
        query_tokens: list[str],
        access_scope: RetrievalAccessScope | None,
    ) -> tuple[list[RetrievalCandidate], dict[str, list], bool]:
        qa_vector = self.repo.search_qa_vector(
            context, query_vector, self.config.vector_top_k, access_scope
        )
        qa_text = self.repo.search_qa_text(
            context, query_tokens, question, self.config.text_top_k, access_scope
        )
        chunk_degraded = False
        try:
            chunk_vector = self.repo.search_chunk_vector(
                context, query_vector, self.config.vector_top_k, access_scope
            )
            chunk_text = self.repo.search_chunk_text(
                context, query_tokens, question, self.config.text_top_k, access_scope
            )
        except ChunkChannelUnavailableError:
            # A declared Chunk-index availability fault is the only permitted
            # fallback.  Never turn ACL/configuration bugs into QA-only results.
            logger.warning(
                "chunk retrieval degraded to qa-only",
                extra={
                    "tenant_id": context.tenant_id,
                    "request_id": current_request_id(),
                    "reason": "chunk_channel_unavailable",
                },
            )
            chunk_vector = []
            chunk_text = []
            chunk_degraded = True

        stages = {
            "qa_vector": qa_vector,
            "qa_text": qa_text,
            "chunk_vector": chunk_vector,
            "chunk_text": chunk_text,
        }
        evidence = self._fuse_evidence(stages)
        return [item.to_candidate() for item in evidence], stages, chunk_degraded

    def _legacy_snapshot(
        self,
        question: str,
        vector_ranked,
        text_ranked,
        fused: list[RetrievalCandidate],
        access_scope: RetrievalAccessScope | None,
        started: float,
        config_hash: str,
    ) -> dict:
        cap = self.config.snapshot_max_items_per_stage
        return {
            "question": question,
            "stages": {
                "vector": [self._rank_snapshot(item, score) for item, score in vector_ranked][:cap],
                "text": [self._rank_snapshot(item, score) for item, score in text_ranked][:cap],
                "rrf": [item.to_snapshot() for item in fused][:cap],
                "rerank": [],
            },
            "filters": self._snapshot_filters(access_scope),
            "channels": ["qa_vector", "qa_text"],
            "configHash": config_hash,
            "featureFlags": {
                "hybridChunkRetrievalEnabled": False,
                "parentContextEnabled": False,
            },
            "latencyMs": int((perf_counter() - started) * 1000),
            "requestId": current_request_id(),
        }

    def _hybrid_snapshot(
        self,
        question: str,
        stages: dict[str, list],
        fused: list[RetrievalCandidate],
        access_scope: RetrievalAccessScope | None,
        started: float,
        chunk_degraded: bool,
        config_hash: str,
    ) -> dict:
        cap = self.config.snapshot_max_items_per_stage
        stage_snapshot = {
            # These two established names remain QA channel snapshots.
            "vector": self._ranked_snapshots(stages["qa_vector"])[:cap],
            "text": self._ranked_snapshots(stages["qa_text"])[:cap],
            "qaVector": self._ranked_snapshots(stages["qa_vector"])[:cap],
            "qaText": self._ranked_snapshots(stages["qa_text"])[:cap],
            "chunkVector": self._ranked_snapshots(stages["chunk_vector"])[:cap],
            "chunkText": self._ranked_snapshots(stages["chunk_text"])[:cap],
            "rrf": [item.to_snapshot() for item in fused][:cap],
            "rerank": [],
        }
        return {
            "question": question,
            "stages": stage_snapshot,
            "filters": self._snapshot_filters(access_scope),
            "channels": list(_CHANNEL_NAMES),
            "configHash": config_hash,
            "featureFlags": {
                "hybridChunkRetrievalEnabled": True,
                "parentContextEnabled": self.parent_context_enabled,
            },
            "rrfParameters": {
                "k": self.config.rrf_k,
                "weights": dict(self.rrf_channel_weights),
            },
            "chunkRetrievalDegraded": chunk_degraded,
            "latencyMs": int((perf_counter() - started) * 1000),
            "requestId": current_request_id(),
        }

    @staticmethod
    def _snapshot_filters(access_scope: RetrievalAccessScope | None) -> dict:
        return {
            "scopeDocumentIds": sorted(access_scope.document_ids)
            if access_scope and access_scope.document_ids
            else None,
            "scopeSpaceId": access_scope.space_id if access_scope else None,
            "scopeClassificationDepartmentId": (
                access_scope.classification_department_id if access_scope else None
            ),
            "scopeCategoryId": access_scope.category_id if access_scope else None,
        }

    def _embed_query(self, tenant_id: str, question: str) -> list[float]:
        try:
            model_config, provider = EmbeddingService(self.session)._default_model(tenant_id)
            adapter = self._build_adapter(
                provider.provider_type,
                provider.base_url,
                decrypt_secret(provider.encrypted_api_key),
                {**(provider.config or {}), **(model_config.config or {})},
                model_name=model_config.model_name,
                timeout_ms=model_config.timeout_ms,
            )
            return adapter.embed_texts([question])[0]
        except Exception:
            # Degraded local/test path: no embedding model configured or the
            # provider is unreachable. Real deployments never reach this.
            return self._fallback_embedding(question, 4)

    def _rrf(self, vector_ranked, text_ranked) -> list[RetrievalCandidate]:
        """Preserve the legacy QA-only RRF path byte-for-byte in behavior."""
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

    def _fuse_evidence(self, channels: Mapping[str, list]) -> list[RetrievalEvidence]:
        """Map all four ranked channels to Child evidence, fuse RRF, then dedupe."""
        source_chunks, parents_by_id = self._load_qa_source_chunks(channels)
        by_chunk_id: dict[str, RetrievalEvidence] = {}
        for channel in _CHANNEL_NAMES:
            for rank, (item, raw_score) in enumerate(channels.get(channel, []), start=1):
                evidence = self._evidence_from_ranked_item(
                    item,
                    source_chunks=source_chunks,
                    parents_by_id=parents_by_id,
                )
                if evidence is None:
                    continue
                contribution = self.rrf_channel_weights[channel] / (self.config.rrf_k + rank)
                evidence = replace(
                    evidence,
                    channel_scores={channel: float(raw_score)},
                    channel_ranks={channel: rank},
                    fused_score=contribution,
                )
                current = by_chunk_id.get(evidence.chunk_id)
                by_chunk_id[evidence.chunk_id] = (
                    evidence if current is None else self._merge_same_chunk(current, evidence)
                )
        return self._deduplicate_evidence(list(by_chunk_id.values()))

    def _load_qa_source_chunks(
        self, channels: Mapping[str, list]
    ) -> tuple[dict[str, DocumentChunk], dict[str, DocumentChunk]]:
        """Bulk-load QA source Children and their Parents for provenance checks."""
        qa_chunk_ids: set[str] = set()
        source_chunks: dict[str, DocumentChunk] = {}
        for ranked in channels.values():
            for item, _score in ranked:
                if isinstance(item, QaPair) and item.chunk_id:
                    qa_chunk_ids.add(item.chunk_id)
                elif isinstance(item, DocumentChunk):
                    source_chunks[item.id] = item

        if qa_chunk_ids:
            source_chunks.update(
                {
                    chunk.id: chunk
                    for chunk in self.session.scalars(
                        select(DocumentChunk).where(DocumentChunk.id.in_(qa_chunk_ids))
                    )
                }
            )
        parent_ids = {
            chunk.parent_chunk_id
            for chunk in source_chunks.values()
            if chunk.parent_chunk_id
        }
        parents_by_id = (
            {
                chunk.id: chunk
                for chunk in self.session.scalars(
                    select(DocumentChunk).where(DocumentChunk.id.in_(parent_ids))
                )
            }
            if parent_ids
            else {}
        )
        return source_chunks, parents_by_id

    def _evidence_from_ranked_item(
        self,
        item: QaPair | DocumentChunk,
        *,
        source_chunks: Mapping[str, DocumentChunk],
        parents_by_id: Mapping[str, DocumentChunk],
    ) -> RetrievalEvidence | None:
        if isinstance(item, QaPair):
            # New QA must carry strict provenance.  Hybrid evidence is always
            # source-Chunk-centric; legacy QA remains available via the flag-off
            # compatibility path.
            if not item.chunk_id:
                return None
            chunk = source_chunks.get(item.chunk_id)
            if not self._is_live_source_chunk(
                chunk, item.tenant_id, item.document_id, parents_by_id
            ):
                return None
            return self._evidence_from_chunk(chunk, qa_pair=item)
        if isinstance(item, DocumentChunk):
            if not self._is_live_source_chunk(
                item, item.tenant_id, item.document_id, parents_by_id
            ):
                return None
            return self._evidence_from_chunk(item)
        raise TypeError(f"Unsupported retrieval item type: {type(item)!r}")

    @staticmethod
    def _is_live_source_chunk(
        chunk: DocumentChunk | None,
        tenant_id: str,
        document_id: str,
        parents_by_id: Mapping[str, DocumentChunk],
    ) -> bool:
        if not (
            chunk
            and chunk.tenant_id == tenant_id
            and chunk.document_id == document_id
            and chunk.status == "ACTIVE"
            and chunk.chunk_level == "CHILD"
        ):
            return False
        if not chunk.parent_chunk_id:
            return True
        parent = parents_by_id.get(chunk.parent_chunk_id)
        return bool(
            parent
            and parent.tenant_id == tenant_id
            and parent.document_id == document_id
            and parent.status == "ACTIVE"
            and parent.chunk_level == "PARENT"
        )

    @staticmethod
    def _evidence_from_chunk(
        chunk: DocumentChunk, qa_pair: QaPair | None = None
    ) -> RetrievalEvidence:
        source_locator = chunk.source_locators or chunk.source_locator or {}
        content_hash = chunk.content_hash
        if not content_hash or content_hash == hashlib.sha256(b"").hexdigest():
            content_hash = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
        return RetrievalEvidence(
            evidence_type="QA" if qa_pair else "CHUNK",
            evidence_id=chunk.id,
            document_id=chunk.document_id,
            chunk_id=chunk.id,
            parent_chunk_id=chunk.parent_chunk_id,
            content=chunk.content,
            quote=qa_pair.quote if qa_pair else None,
            title_path=tuple(str(item) for item in (chunk.title_path or [])),
            page_start=chunk.page_start or chunk.page_no,
            page_end=chunk.page_end or chunk.page_no,
            source_locator=source_locator,
            channel_scores={},
            channel_ranks={},
            fused_score=0.0,
            content_hash=content_hash,
            qa_pair_id=qa_pair.id if qa_pair else None,
            question=qa_pair.question if qa_pair else None,
            answer=qa_pair.answer if qa_pair else None,
            pair_index=qa_pair.pair_index if qa_pair else chunk.chunk_index,
        )

    @staticmethod
    def _merge_same_chunk(
        left: RetrievalEvidence, right: RetrievalEvidence
    ) -> RetrievalEvidence:
        # RRF contributions for the same Child add.  Prefer the QA-bearing
        # representation for legacy Candidate/citation compatibility.
        metadata = right if right.qa_pair_id and not left.qa_pair_id else left
        return replace(
            metadata,
            evidence_type="QA" if left.qa_pair_id or right.qa_pair_id else "CHUNK",
            channel_scores={**left.channel_scores, **right.channel_scores},
            channel_ranks={**left.channel_ranks, **right.channel_ranks},
            fused_score=left.fused_score + right.fused_score,
        )

    def _deduplicate_evidence(
        self, evidence: list[RetrievalEvidence]
    ) -> list[RetrievalEvidence]:
        """Deduplicate in the required order: span, hash, then overlap.

        Exact ``chunk_id`` duplicates were already merged before this method.
        For broader duplicate relations the strongest fused evidence is kept
        while its channel provenance is merged with the weaker duplicate.
        """
        kept: list[RetrievalEvidence] = []
        for candidate in sorted(
            evidence, key=lambda item: (-item.fused_score, item.document_id, item.chunk_id)
        ):
            duplicate_index = next(
                (
                    index
                    for index, existing in enumerate(kept)
                    if self._same_source_span(existing, candidate)
                ),
                None,
            )
            if duplicate_index is None:
                duplicate_index = next(
                    (
                        index
                        for index, existing in enumerate(kept)
                        if self._same_content_hash(existing, candidate)
                    ),
                    None,
                )
            if duplicate_index is None:
                duplicate_index = next(
                    (
                        index
                        for index, existing in enumerate(kept)
                        if self._highly_overlapping_span(existing, candidate)
                    ),
                    None,
                )
            if duplicate_index is None:
                kept.append(candidate)
            else:
                kept[duplicate_index] = self._merge_duplicate_evidence(
                    kept[duplicate_index], candidate
                )
        return sorted(kept, key=lambda item: (-item.fused_score, item.document_id, item.chunk_id))

    @staticmethod
    def _merge_duplicate_evidence(
        left: RetrievalEvidence, right: RetrievalEvidence
    ) -> RetrievalEvidence:
        # Cross-Chunk deduplication retains the strongest source identity in
        # full.  Channel provenance is the only metadata that may be merged:
        # otherwise a lower-ranked QA can incorrectly replace a winning Chunk's
        # document, locator, quote, or citation target.
        winner = left if left.fused_score >= right.fused_score else right
        return replace(
            winner,
            channel_scores={**left.channel_scores, **right.channel_scores},
            channel_ranks={**left.channel_ranks, **right.channel_ranks},
            fused_score=winner.fused_score,
        )

    @staticmethod
    def _same_source_span(left: RetrievalEvidence, right: RetrievalEvidence) -> bool:
        return (
            left.document_id == right.document_id
            and RetrievalService._source_span_key(left.source_locator) is not None
            and RetrievalService._source_span_key(left.source_locator)
            == RetrievalService._source_span_key(right.source_locator)
        )

    @staticmethod
    def _same_content_hash(left: RetrievalEvidence, right: RetrievalEvidence) -> bool:
        # Retrieval scope already guarantees tenant isolation.  Identical source
        # content is redundant even when it appears in separate documents.
        return bool(left.content_hash and left.content_hash == right.content_hash)

    @staticmethod
    def _source_span_key(source_locator: dict | list[dict]) -> str | None:
        if not source_locator:
            return None
        return json.dumps(source_locator, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _highly_overlapping_span(left: RetrievalEvidence, right: RetrievalEvidence) -> bool:
        if left.document_id != right.document_id:
            return False
        for left_block, left_start, left_end in RetrievalService._locator_ranges(left.source_locator):
            for right_block, right_start, right_end in RetrievalService._locator_ranges(right.source_locator):
                if left_block != right_block:
                    continue
                overlap = max(0, min(left_end, right_end) - max(left_start, right_start))
                shorter = min(left_end - left_start, right_end - right_start)
                if shorter > 0 and overlap / shorter >= 0.8:
                    return True
        return False

    @staticmethod
    def _locator_ranges(source_locator: dict | list[dict]) -> list[tuple[str | int | None, int, int]]:
        locators = source_locator if isinstance(source_locator, list) else [source_locator]
        ranges: list[tuple[str | int | None, int, int]] = []
        for locator in locators:
            if not isinstance(locator, dict):
                continue
            span = locator.get("_lingxi_chunk_span")
            if not isinstance(span, dict):
                continue
            start = span.get("merged_char_start", span.get("source_rel_start"))
            end = span.get("merged_char_end", span.get("source_rel_end"))
            if isinstance(start, int) and isinstance(end, int) and end > start:
                ranges.append((locator.get("block"), start, end))
        return ranges

    @staticmethod
    def _normalize_channel_weights(
        weights: Mapping[str, float] | None,
    ) -> dict[str, float]:
        resolved = dict(_DEFAULT_RRF_CHANNEL_WEIGHTS)
        if weights is None:
            return resolved
        unknown = set(weights) - set(_CHANNEL_NAMES)
        if unknown:
            raise ValueError(f"Unknown RRF channel weights: {sorted(unknown)}")
        for channel, value in weights.items():
            value = float(value)
            if not math.isfinite(value) or value < 0:
                raise ValueError(
                    f"RRF channel weight must be a finite non-negative number: {channel}"
                )
            resolved[channel] = value
        return resolved

    @staticmethod
    def _fallback_embedding(text: str, dimension: int) -> list[float]:
        values = [float((ord(char) % 29) + 1) for char in text[:dimension]]
        values.extend([0.0] * (dimension - len(values)))
        return values[:dimension]

    @staticmethod
    def _rank_snapshot(item, score: float, rank: int | None = None) -> dict:
        if isinstance(item, QaPair):
            snapshot = {
                "qaPairId": item.id,
                "documentId": item.document_id,
                "question": item.question,
                "score": round(score, 6),
            }
        elif isinstance(item, DocumentChunk):
            snapshot = {
                "chunkId": item.id,
                "documentId": item.document_id,
                "pageStart": item.page_start or item.page_no,
                "pageEnd": item.page_end or item.page_no,
                "titlePath": list(item.title_path or []),
                "score": round(score, 6),
            }
        else:
            raise TypeError(f"Unsupported retrieval item type: {type(item)!r}")
        if rank is not None:
            snapshot["rank"] = rank
        return snapshot

    def _ranked_snapshots(self, ranked: list) -> list[dict]:
        return [
            self._rank_snapshot(item, score, rank)
            for rank, (item, score) in enumerate(ranked, start=1)
        ]

    def _observability_config_hash(self) -> str:
        payload = {
            "retrieval": {
                "vectorTopK": self.config.vector_top_k,
                "textTopK": self.config.text_top_k,
                "finalTopK": self.config.final_top_k,
                "rrfK": self.config.rrf_k,
                "lowConfidenceThreshold": self.config.low_confidence_threshold,
                "snapshotMaxItemsPerStage": self.config.snapshot_max_items_per_stage,
            },
            "featureFlags": {
                "hybridChunkRetrievalEnabled": self.hybrid_chunk_retrieval_enabled,
                "parentContextEnabled": self.parent_context_enabled,
            },
            "rrfChannelWeights": self.rrf_channel_weights,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _hydration_token_count(
        self, candidates: list[RetrievalCandidate]
    ) -> int:
        return sum(
            len(self.tokenizer.tokenize(segment.content))
            for candidate in candidates
            for segment in getattr(candidate, "_lingxi_context_segments", ())
        )


def normalize_retrieval_scope(
    access_scope: RetrievalAccessScope | None,
) -> RetrievalAccessScope | None:
    if access_scope is None:
        return None
    if access_scope.classification_department_id and not access_scope.space_id:
        raise ValueError(
            "classification_department_id requires space_id in retrieval scope"
        )
    if access_scope.category_id and (
        not access_scope.space_id or not access_scope.classification_department_id
    ):
        raise ValueError(
            "category_id requires space_id and classification_department_id in retrieval scope"
        )
    return access_scope


def _scope_log_fields(access_scope: RetrievalAccessScope | None) -> dict:
    return {
        "scope_space_id": access_scope.space_id if access_scope else None,
        "scope_classification_department_id": (
            access_scope.classification_department_id if access_scope else None
        ),
        "scope_category_id": access_scope.category_id if access_scope else None,
    }
