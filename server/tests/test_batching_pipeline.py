import types

import pytest

import server.app.db.base  # noqa: F401
from server.app.integrations.model_providers.base import ProviderError
from server.app.integrations.model_providers.registry import build_provider_adapter


def _embedding_settings(batch_size, concurrency=1, retries=2):
    return types.SimpleNamespace(
        embedding_batch_size=batch_size,
        embedding_max_concurrency=concurrency,
        embedding_batch_max_retries=retries,
    )


def test_embed_in_batches_preserves_order_across_batches(monkeypatch):
    from server.app.services import embedding_service
    from server.app.services.embedding_service import EmbeddingService
    from server.tests.test_qa_split_task import build_qa_session

    monkeypatch.setattr(embedding_service, "settings", _embedding_settings(batch_size=2))

    session, _identity = build_qa_session()
    adapter = build_provider_adapter(
        "OPENAI_COMPATIBLE", "mock://success", None, {"embeddingDimension": 4}
    )
    questions = [f"q{i}" for i in range(5)]  # 5 items, batch_size 2 -> 3 batches

    vectors = EmbeddingService(session)._embed_in_batches(adapter, questions, 4)

    assert len(vectors) == 5
    assert all(len(v) == 4 for v in vectors)
    # MockProvider is deterministic per text, so batched == per-text order
    expected = [adapter.embed_texts([q])[0] for q in questions]
    assert vectors == expected


class _FlakyAdapter:
    def __init__(self, fail_times: int, retryable: bool = True) -> None:
        self.calls = 0
        self.fail_times = fail_times
        self.retryable = retryable

    def embed_texts(self, batch):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ProviderError("PROVIDER_RATE_LIMITED", "slow", retryable=self.retryable)
        return [[0.0, 0.0, 0.0, 0.0] for _ in batch]


def test_embed_batch_retries_transient_failures(monkeypatch):
    from server.app.services import embedding_service
    from server.app.services.embedding_service import EmbeddingService
    from server.tests.test_qa_split_task import build_qa_session

    monkeypatch.setattr(embedding_service, "settings", _embedding_settings(batch_size=64, retries=2))
    monkeypatch.setattr(embedding_service.time, "sleep", lambda *_: None)

    session, _identity = build_qa_session()
    adapter = _FlakyAdapter(fail_times=2)

    vectors = EmbeddingService(session)._embed_batch_with_retry(adapter, ["a"], 4)
    assert len(vectors) == 1
    assert adapter.calls == 3  # 2 failures + 1 success


def test_embed_batch_gives_up_on_non_retryable(monkeypatch):
    from server.app.services import embedding_service
    from server.app.services.embedding_service import (
        EmbeddingService,
        EmbeddingServiceError,
    )
    from server.tests.test_qa_split_task import build_qa_session

    monkeypatch.setattr(embedding_service, "settings", _embedding_settings(batch_size=64, retries=3))
    monkeypatch.setattr(embedding_service.time, "sleep", lambda *_: None)

    session, _identity = build_qa_session()
    adapter = _FlakyAdapter(fail_times=1, retryable=False)

    with pytest.raises(EmbeddingServiceError):
        EmbeddingService(session)._embed_batch_with_retry(adapter, ["a"], 4)
    assert adapter.calls == 1  # non-retryable -> no retry


def test_group_chunks_packs_by_char_budget(monkeypatch):
    from server.app.services import qa_split_service
    from server.app.services.qa_split_service import QaSplitService
    from server.tests.test_qa_split_task import build_qa_session

    monkeypatch.setattr(
        qa_split_service,
        "settings",
        types.SimpleNamespace(qa_split_max_batch_chars=10, qa_split_max_concurrency=1),
    )

    session, _identity = build_qa_session()
    chunks = [types.SimpleNamespace(content="x" * 6) for _ in range(5)]  # 6 chars each

    groups = QaSplitService(session)._group_chunks(chunks)

    # budget 10, each chunk 6 chars -> only one chunk fits per group
    assert [len(g) for g in groups] == [1, 1, 1, 1, 1]
    # total chunks preserved
    assert sum(len(g) for g in groups) == 5


def test_group_chunks_oversized_chunk_forms_own_group(monkeypatch):
    from server.app.services import qa_split_service
    from server.app.services.qa_split_service import QaSplitService
    from server.tests.test_qa_split_task import build_qa_session

    monkeypatch.setattr(
        qa_split_service,
        "settings",
        types.SimpleNamespace(qa_split_max_batch_chars=10, qa_split_max_concurrency=1),
    )

    session, _identity = build_qa_session()
    chunks = [
        types.SimpleNamespace(content="ab"),  # 2
        types.SimpleNamespace(content="x" * 50),  # oversized -> own group
        types.SimpleNamespace(content="cd"),  # 2
    ]

    groups = QaSplitService(session)._group_chunks(chunks)

    assert [[c.content for c in g] for g in groups] == [
        ["ab"],
        ["x" * 50],
        ["cd"],
    ]



def test_group_chunks_rejects_oversized_adaptive_chunk_before_qa(monkeypatch):
    import types

    import pytest

    from server.app.services import qa_split_service
    from server.app.services.qa_split_service import QaSplitService, QaSplitValidationError
    from server.tests.test_qa_split_task import build_qa_session

    monkeypatch.setattr(
        qa_split_service,
        "settings",
        types.SimpleNamespace(qa_split_max_batch_chars=10, qa_split_max_concurrency=1),
    )
    session, _identity = build_qa_session()
    chunk = types.SimpleNamespace(
        content="x" * 11,
        chunker_name="adaptive_hierarchical",
        chunk_index=42,
    )

    with pytest.raises(QaSplitValidationError, match="超出"):
        QaSplitService(session)._group_chunks([chunk])
