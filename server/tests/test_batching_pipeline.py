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


class _CharacterTokenCounter:
    name = "test-character-counter"
    version = "1.0"

    def count(self, text: str) -> int:
        return len(text)

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        return [text[index : index + limit] for index in range(0, len(text), limit)]


def _qa_batching_chunk(index: int, content: str, content_hash: str):
    return types.SimpleNamespace(
        chunk_index=index,
        content=content,
        content_hash=content_hash,
        page_no=index + 1,
        page_start=None,
        page_end=None,
        title_path=[f"Section {index}"],
        chunker_name="legacy_parser",
        chunker_config_hash="generation-a",
        chunk_metadata={},
    )


def test_token_batching_counts_fixed_prompt_title_and_chunk_metadata():
    from server.app.models.document import Document
    from server.app.services.qa_prompt_builder import build_qa_split_prompt
    from server.app.services.qa_split_batching import estimate_qa_prompt_tokens

    counter = _CharacterTokenCounter()
    document = Document(title="A title that must be budgeted")
    chunk = _qa_batching_chunk(7, "body", "a" * 64)

    estimated = estimate_qa_prompt_tokens(document, [chunk], counter)

    assert estimated == counter.count(build_qa_split_prompt(document, [chunk]))
    assert estimated > counter.count(chunk.content)
    assert document.title in build_qa_split_prompt(document, [chunk])
    assert "pageRange=" in build_qa_split_prompt(document, [chunk])


def test_token_batching_sorts_indexes_and_keeps_hash_stable(monkeypatch):
    from server.app.models.document import Document
    from server.app.services import qa_split_batching
    from server.app.services.qa_split_batching import (
        estimate_qa_prompt_tokens,
        group_qa_chunks,
        split_qa_batch,
    )

    counter = _CharacterTokenCounter()
    document = Document(title="Stable")
    first = _qa_batching_chunk(10, "alpha", "a" * 64)
    second = _qa_batching_chunk(2, "bravo", "b" * 64)
    max_input_tokens = estimate_qa_prompt_tokens(document, [first, second], counter)

    batches = group_qa_chunks(
        document,
        [first, second],
        token_counter=counter,
        max_input_tokens=max_input_tokens,
        reserved_output_tokens=12,
    )
    repeated = group_qa_chunks(
        document,
        [second, first],
        token_counter=counter,
        max_input_tokens=max_input_tokens,
        reserved_output_tokens=12,
    )
    left, right = split_qa_batch(batches[0])
    monkeypatch.setattr(
        qa_split_batching,
        "QA_SPLIT_PROMPT_VERSION",
        "qa-split-v3",
    )
    changed_version = group_qa_chunks(
        document,
        [first, second],
        token_counter=counter,
        max_input_tokens=max_input_tokens,
        reserved_output_tokens=12,
    )

    assert [[chunk.chunk_index for chunk in batch.chunks] for batch in batches] == [[2, 10]]
    assert batches[0].input_hash == repeated[0].input_hash
    assert changed_version[0].input_hash != batches[0].input_hash
    assert len(batches[0].input_hash) == 64
    assert [chunk.chunk_index for chunk in (*left.chunks, *right.chunks)] == [2, 10]
    assert {chunk.chunk_index for chunk in (*left.chunks, *right.chunks)} == {2, 10}


def test_token_batching_rejects_oversized_adaptive_chunk():
    from server.app.models.document import Document
    from server.app.services.qa_split_batching import (
        QA_PROVENANCE_CONTRACT_INVALID,
        QaBatchingError,
        estimate_qa_prompt_tokens,
        group_qa_chunks,
    )

    counter = _CharacterTokenCounter()
    document = Document(title="Adaptive")
    chunk = _qa_batching_chunk(4, "x" * 20, "c" * 64)
    chunk.chunker_name = "adaptive_hierarchical"
    max_input_tokens = estimate_qa_prompt_tokens(
        document,
        [_qa_batching_chunk(4, "", "c" * 64)],
        counter,
    ) + 1

    with pytest.raises(QaBatchingError) as exc_info:
        group_qa_chunks(
            document,
            [chunk],
            token_counter=counter,
            max_input_tokens=max_input_tokens,
            reserved_output_tokens=0,
        )

    assert exc_info.value.code == QA_PROVENANCE_CONTRACT_INVALID
    assert exc_info.value.retryable is False


def _retryable_qa_batch(*chunks):
    from server.app.services.qa_split_batching import QaBatch, qa_batch_input_hash

    return QaBatch(
        batch_index=7,
        chunks=tuple(chunks),
        estimated_input_tokens=100,
        reserved_output_tokens=20,
        input_hash=qa_batch_input_hash(chunks),
    )


def test_qa_batch_retries_timeout_once_then_returns_success(monkeypatch):
    from server.app.services import qa_split_batching
    from server.app.services.qa_split_batching import execute_qa_batch_with_retry

    batch = _retryable_qa_batch(_qa_batching_chunk(1, "alpha", "a" * 64))

    class Adapter:
        calls = 0

        def generate_qa_pairs(self, _batch):
            type(self).calls += 1
            if type(self).calls == 1:
                raise ProviderError(
                    "PROVIDER_INFERENCE_TIMEOUT",
                    "inference timeout",
                    retryable=True,
                )
            return "success"

    monkeypatch.setattr(qa_split_batching.time, "sleep", lambda _seconds: None)
    result = execute_qa_batch_with_retry(
        Adapter(), batch, max_retries=1, max_split_depth=1
    )

    assert Adapter.calls == 2
    assert result.raw_output == "success"
    assert result.error is None
    assert result.retry_count == 1


def test_qa_batch_429_retry_after_is_capped(monkeypatch):
    from server.app.services import qa_split_batching
    from server.app.services.qa_split_batching import execute_qa_batch_with_retry

    batch = _retryable_qa_batch(_qa_batching_chunk(1, "alpha", "a" * 64))
    delays = []

    class Adapter:
        calls = 0

        def generate_qa_pairs(self, _batch):
            type(self).calls += 1
            if type(self).calls == 1:
                error = ProviderError(
                    "PROVIDER_RATE_LIMITED", "slow down", retryable=True
                )
                error.retry_after_seconds = 300
                raise error
            return "success"

    monkeypatch.setattr(
        qa_split_batching.time, "sleep", lambda seconds: delays.append(seconds)
    )
    result = execute_qa_batch_with_retry(
        Adapter(), batch, max_retries=1, max_split_depth=0
    )

    assert Adapter.calls == 2
    assert result.error is None
    assert delays == [30.0]


def test_qa_batch_does_not_retry_unauthorized_error():
    from server.app.services.qa_split_batching import execute_qa_batch_with_retry

    batch = _retryable_qa_batch(_qa_batching_chunk(1, "alpha", "a" * 64))

    class Adapter:
        calls = 0

        def generate_qa_pairs(self, _batch):
            type(self).calls += 1
            raise ProviderError(
                "PROVIDER_UNAUTHORIZED", "unauthorized", retryable=False
            )

    result = execute_qa_batch_with_retry(
        Adapter(), batch, max_retries=3, max_split_depth=3
    )

    assert Adapter.calls == 1
    assert result.error is not None
    assert result.error.code == "PROVIDER_UNAUTHORIZED"
    assert result.split_results == ()


def test_qa_single_chunk_timeout_does_not_split_or_recurse():
    from server.app.services.qa_split_batching import execute_qa_batch_with_retry

    batch = _retryable_qa_batch(_qa_batching_chunk(1, "alpha", "a" * 64))

    class Adapter:
        calls = 0

        def generate_qa_pairs(self, _batch):
            type(self).calls += 1
            raise ProviderError(
                "PROVIDER_INFERENCE_TIMEOUT",
                "inference timeout",
                retryable=True,
            )

    result = execute_qa_batch_with_retry(
        Adapter(), batch, max_retries=0, max_split_depth=10
    )

    assert Adapter.calls == 1
    assert result.error is not None
    assert result.split_results == ()
    assert len(result.leaf_results()) == 1


def test_backpressure_reduces_concurrency_and_recovers_in_order(monkeypatch):
    from server.app.services import qa_split_backpressure
    from server.app.services.qa_split_backpressure import (
        BackpressureState,
        run_ordered_with_backpressure,
    )

    monkeypatch.setattr(qa_split_backpressure.time, "sleep", lambda _seconds: None)
    state = BackpressureState(
        current_concurrency=4,
        min_concurrency=1,
        max_concurrency=4,
    )

    def worker(item):
        if item < 4:
            return types.SimpleNamespace(
                error=ProviderError(
                    "PROVIDER_RATE_LIMITED",
                    "rate limited",
                    retryable=True,
                ),
                value=item,
            )
        return types.SimpleNamespace(error=None, value=item)

    results = run_ordered_with_backpressure(range(7), worker, state)

    assert [result.value for result in results] == list(range(7))
    assert state.current_concurrency == 2
    assert state.consecutive_successes == 0


def test_backpressure_state_isolated_by_provider_and_model():
    from server.app.services.qa_split_backpressure import (
        get_backpressure_state,
        reset_backpressure_states,
    )

    reset_backpressure_states()
    first = get_backpressure_state(
        "provider-a",
        "model-a",
        current_concurrency=4,
        min_concurrency=1,
        max_concurrency=4,
    )
    second = get_backpressure_state(
        "provider-b",
        "model-b",
        current_concurrency=4,
        min_concurrency=1,
        max_concurrency=4,
    )

    first.on_retryable_failure("PROVIDER_OVERALL_TIMEOUT")

    assert first.current_concurrency == 2
    assert second.current_concurrency == 4


def test_backpressure_state_recovers_one_level_after_three_successes():
    from server.app.services.qa_split_backpressure import BackpressureState

    state = BackpressureState(
        current_concurrency=1,
        min_concurrency=1,
        max_concurrency=4,
    )

    assert state.on_success() == 1
    assert state.on_success() == 1
    assert state.on_success() == 2
    assert state.consecutive_successes == 0
