import server.app.db.base  # noqa: F401


def test_embedding_service_uses_injected_provider_factory():
    from server.app.integrations.model_providers.registry import build_provider_adapter
    from server.app.services.embedding_service import EmbeddingService
    from server.tests.test_embedding_task import (
        add_default_embedding_model,
        add_qa_pairs,
        prepare_embedding_job,
    )
    from server.tests.test_qa_split_task import build_qa_session

    session, identity = build_qa_session()
    tenant_id = identity["tenant"].id
    job_id, document_id, chunks = prepare_embedding_job(session, identity)
    add_default_embedding_model(session, tenant_id, expected_dimension=4)
    add_qa_pairs(session, tenant_id, document_id, job_id, [c.id for c in chunks])

    calls: list[tuple] = []

    def fake_factory(*args, **kwargs):
        calls.append((args, kwargs))
        return build_provider_adapter(*args, **kwargs)

    job = EmbeddingService(session, provider_factory=fake_factory).embed_import_job(job_id)

    # The injected factory was used instead of the module-level default.
    assert job.status == "COMPLETED"
    assert calls, "injected provider_factory should have been called"


def test_retrieval_service_accepts_injected_reranker_and_factory():
    from server.app.services.rerank_service import RerankService
    from server.app.services.retrieval_service import RetrievalService
    from server.tests.test_document_permissions import build_session

    session, _identity = build_session()

    class _CountingReranker(RerankService):
        def __init__(self) -> None:
            self.calls = 0

        def rerank(self, query, candidates):
            self.calls += 1
            return super().rerank(query, candidates)

    reranker = _CountingReranker()
    factory_calls: list = []

    def fake_factory(*args, **kwargs):
        factory_calls.append(args)
        raise RuntimeError("no embedding model in this test")  # forces fallback path

    service = RetrievalService(session, reranker=reranker, provider_factory=fake_factory)
    assert service.reranker is reranker
    assert service._build_adapter is fake_factory


def test_service_dependencies_centrally_select_legacy_or_adaptive_and_flags(monkeypatch):
    from server.app.core.config import Settings
    from server.app.core.service_factory import (
        build_document_parse_service,
        build_embedding_service,
        build_qa_split_service,
        build_retrieval_service,
    )

    for name in (
        "CHUNKING_MODE", "QA_STRICT_PROVENANCE_ENABLED", "CHUNK_INDEXING_ENABLED",
        "HYBRID_CHUNK_RETRIEVAL_ENABLED", "PARENT_CONTEXT_ENABLED",
        "CHUNK_MIN_TOKENS", "CHUNK_TARGET_TOKENS", "CHUNK_MAX_TOKENS",
        "CHUNK_OVERLAP_TOKENS", "CHUNK_PARENT_MAX_TOKENS",
        "RETRIEVAL_QA_VECTOR_WEIGHT", "RETRIEVAL_QA_TEXT_WEIGHT",
        "RETRIEVAL_CHUNK_VECTOR_WEIGHT", "RETRIEVAL_CHUNK_TEXT_WEIGHT",
    ):
        monkeypatch.delenv(name, raising=False)

    legacy_settings = Settings()
    legacy_parse = build_document_parse_service(object(), settings=legacy_settings)
    legacy_retrieval = build_retrieval_service(object(), settings=legacy_settings)
    assert legacy_parse.adaptive_chunking is False
    assert legacy_parse.chunking_policy is None
    assert legacy_retrieval.hybrid_chunk_retrieval_enabled is False
    assert legacy_retrieval.parent_context_enabled is False
    assert build_qa_split_service(object(), settings=legacy_settings).legacy_missing_chunk_index_compatibility is True
    assert build_embedding_service(object(), settings=legacy_settings).chunk_indexing_enabled is False

    monkeypatch.setenv("CHUNKING_MODE", "adaptive")
    monkeypatch.setenv("QA_STRICT_PROVENANCE_ENABLED", "true")
    monkeypatch.setenv("CHUNK_INDEXING_ENABLED", "true")
    monkeypatch.setenv("HYBRID_CHUNK_RETRIEVAL_ENABLED", "true")
    monkeypatch.setenv("PARENT_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("CHUNK_MIN_TOKENS", "120")
    monkeypatch.setenv("CHUNK_TARGET_TOKENS", "480")
    monkeypatch.setenv("CHUNK_MAX_TOKENS", "840")
    monkeypatch.setenv("CHUNK_OVERLAP_TOKENS", "32")
    monkeypatch.setenv("CHUNK_PARENT_MAX_TOKENS", "1900")
    monkeypatch.setenv("RETRIEVAL_QA_VECTOR_WEIGHT", "0.5")
    monkeypatch.setenv("RETRIEVAL_QA_TEXT_WEIGHT", "0.0")
    monkeypatch.setenv("RETRIEVAL_CHUNK_VECTOR_WEIGHT", "1.5")
    monkeypatch.setenv("RETRIEVAL_CHUNK_TEXT_WEIGHT", "2.0")

    adaptive_settings = Settings()
    adaptive_parse = build_document_parse_service(object(), settings=adaptive_settings)
    adaptive_retrieval = build_retrieval_service(object(), settings=adaptive_settings)
    assert adaptive_parse.adaptive_chunking is True
    assert adaptive_parse.chunking_policy.min_tokens == 120
    assert adaptive_parse.chunking_policy.target_tokens == 480
    assert adaptive_parse.chunking_policy.max_tokens == 840
    assert adaptive_parse.chunking_policy.overlap_tokens == 32
    assert adaptive_parse.chunking_policy.parent_max_tokens == 1900
    assert adaptive_parse.chunking_service._token_counter.name == adaptive_settings.chunk_tokenizer_name
    assert adaptive_retrieval.hybrid_chunk_retrieval_enabled is True
    assert adaptive_retrieval.parent_context_enabled is True
    assert adaptive_retrieval.context_hydration_service is not None
    assert adaptive_retrieval.rrf_channel_weights == {
        "qa_vector": 0.5,
        "qa_text": 0.0,
        "chunk_vector": 1.5,
        "chunk_text": 2.0,
    }
    assert build_qa_split_service(object(), settings=adaptive_settings).legacy_missing_chunk_index_compatibility is False
    assert build_embedding_service(object(), settings=adaptive_settings).chunk_indexing_enabled is True
