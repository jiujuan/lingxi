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
