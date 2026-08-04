from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from server.app.core.config import Settings, settings as runtime_settings, validate_chunking_config
from server.app.core.retrieval_config import RetrievalConfig, get_retrieval_config
from server.app.services.chunking import (
    ChunkPolicy,
    ChunkingService,
    LocalTokenCounter,
    TokenizerUnavailableError,
)
from server.app.services.context_hydration_service import ContextHydrationService
from server.app.services.document_parse_service import DocumentParseService
from server.app.services.embedding_service import EmbeddingService
from server.app.services.qa_split_service import QaSplitService
from server.app.services.retrieval_service import RetrievalService


@dataclass(frozen=True)
class ServiceDependencies:
    """The resolved, Settings-backed dependencies for adaptive retrieval flows.

    This is the only composition boundary that turns environment-derived
    configuration into business-service constructor arguments.  Services retain
    explicit injectable inputs so tests and non-default callers never need to
    read process environment variables.
    """

    settings: Settings

    @classmethod
    def from_settings(cls, current: Settings | None = None) -> "ServiceDependencies":
        resolved = current or runtime_settings
        validate_chunking_config(resolved)
        return cls(settings=resolved)

    @property
    def adaptive_chunking_enabled(self) -> bool:
        return self.settings.chunking_mode == "adaptive"

    def build_token_counter(self) -> LocalTokenCounter:
        counter = LocalTokenCounter()
        if counter.name != self.settings.chunk_tokenizer_name:
            # The local tokenizer is currently the only deterministic tokenizer
            # implementation.  Refuse a misleading name instead of producing a
            # policy config hash that does not match the runtime counter.
            raise RuntimeError(
                "configured CHUNK_TOKENIZER_NAME does not match the resolved tokenizer"
            )
        return counter

    def build_chunk_policy(self, counter: LocalTokenCounter | None = None) -> ChunkPolicy:
        counter = counter or self.build_token_counter()
        return ChunkPolicy(
            tokenizer_name=counter.name,
            tokenizer_version=counter.version,
            min_tokens=self.settings.chunk_min_tokens,
            target_tokens=self.settings.chunk_target_tokens,
            max_tokens=self.settings.chunk_max_tokens,
            overlap_tokens=self.settings.chunk_overlap_tokens,
            parent_max_tokens=self.settings.chunk_parent_max_tokens,
            semantic_split_enabled=self.settings.chunk_semantic_split_enabled,
        )

    def build_document_parse_service(self, session: Session, **kwargs) -> DocumentParseService:
        if not self.adaptive_chunking_enabled:
            return DocumentParseService(session, adaptive_chunking=False, **kwargs)
        counter = self.build_token_counter()
        return DocumentParseService(
            session,
            adaptive_chunking=True,
            chunking_service=ChunkingService(counter),
            chunking_policy=self.build_chunk_policy(counter),
            **kwargs,
        )

    def build_retrieval_service(
        self,
        session: Session,
        *,
        config: RetrievalConfig | None = None,
        **kwargs,
    ) -> RetrievalService:
        hybrid = self.settings.hybrid_chunk_retrieval_enabled
        parent_context = self.settings.parent_context_enabled
        hydrator = kwargs.pop("context_hydration_service", None)
        if hybrid and parent_context and hydrator is None:
            hydrator = ContextHydrationService(
                session,
                token_counter=self.build_token_counter(),
                parent_max_tokens_per_hit=self.settings.chunk_parent_max_tokens,
            )
        return RetrievalService(
            session,
            config=config or get_retrieval_config(self.settings),
            hybrid_chunk_retrieval_enabled=hybrid,
            parent_context_enabled=parent_context,
            rrf_channel_weights=self.settings.retrieval_rrf_channel_weights,
            context_hydration_service=hydrator,
            **kwargs,
        )

    def build_qa_split_service(self, session: Session, **kwargs) -> QaSplitService:
        token_counter = kwargs.pop("token_counter", None)
        if token_counter is None:
            try:
                token_counter = self.build_token_counter()
            except TokenizerUnavailableError:
                # QA keeps a bounded character fallback for deployments where
                # the pinned local tokenizer is temporarily unavailable.
                token_counter = None
        return QaSplitService(
            session,
            # Strict provenance disabled remains compatible with existing
            # documents generated before chunk indexes were persisted.
            legacy_missing_chunk_index_compatibility=(
                not self.settings.qa_strict_provenance_enabled
            ),
            token_counter=token_counter,
            max_input_tokens=self.settings.qa_split_max_input_tokens,
            reserved_output_tokens=self.settings.qa_split_reserved_output_tokens,
            max_batch_chars=self.settings.qa_split_max_batch_chars,
            initial_concurrency=self.settings.qa_split_initial_concurrency,
            min_concurrency=self.settings.qa_split_min_concurrency,
            max_concurrency=self.settings.qa_split_max_concurrency,
            max_retries=self.settings.qa_split_max_retries,
            max_split_depth=self.settings.qa_split_max_split_depth,
            **kwargs,
        )

    def build_embedding_service(self, session: Session, **kwargs) -> EmbeddingService:
        token_counter = kwargs.pop("token_counter", None)
        if self.settings.chunk_indexing_enabled and token_counter is None:
            token_counter = self.build_token_counter()
        return EmbeddingService(
            session,
            chunk_indexing_enabled=self.settings.chunk_indexing_enabled,
            token_counter=token_counter,
            **kwargs,
        )


def _dependencies(current: Settings | None) -> ServiceDependencies:
    return ServiceDependencies.from_settings(current)


def build_document_parse_service(
    session: Session, *, settings: Settings | None = None, **kwargs
) -> DocumentParseService:
    return _dependencies(settings).build_document_parse_service(session, **kwargs)


def build_retrieval_service(
    session: Session, *, settings: Settings | None = None, **kwargs
) -> RetrievalService:
    return _dependencies(settings).build_retrieval_service(session, **kwargs)


def build_qa_split_service(
    session: Session, *, settings: Settings | None = None, **kwargs
) -> QaSplitService:
    return _dependencies(settings).build_qa_split_service(session, **kwargs)


def build_embedding_service(
    session: Session, *, settings: Settings | None = None, **kwargs
) -> EmbeddingService:
    return _dependencies(settings).build_embedding_service(session, **kwargs)
