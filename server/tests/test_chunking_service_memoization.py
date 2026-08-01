from __future__ import annotations

from dataclasses import dataclass, field

from server.app.services.chunking import (
    AtomicBlock,
    BlockType,
    ChunkPolicy,
    ChunkingService,
)


@dataclass
class CountingCharacterTokenCounter:
    name: str = "counting-character-fixture"
    version: str = "1.0"
    count_inputs: list[str] = field(default_factory=list)

    def count(self, text: str) -> int:
        self.count_inputs.append(text)
        return len(text)

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        return [text[index : index + limit] for index in range(0, len(text), limit)]


def _block(index: int, content: str) -> AtomicBlock:
    return AtomicBlock(
        index=index,
        content=content,
        block_type=BlockType.TEXT,
        source_locator={"sourceIdentity": "memoization.md", "block": index},
        page_no=1,
        title_path=("Memoization",),
        parent_structural_id="memoization-section",
    )


def test_chunking_service_counts_each_exact_text_once_per_chunk_operation() -> None:
    counter = CountingCharacterTokenCounter()
    policy = ChunkPolicy(
        tokenizer_name=counter.name,
        tokenizer_version=counter.version,
        min_tokens=4,
        target_tokens=8,
        max_tokens=10,
        overlap_tokens=2,
        parent_max_tokens=20,
        embedding_provider_input_limit=40,
    )

    result = ChunkingService(counter).chunk(
        (
            _block(0, "alpha"),
            _block(1, "beta"),
            _block(2, "gamma"),
        ),
        policy,
        document_title="Memoization",
    )

    assert result.children
    assert len(counter.count_inputs) == len(set(counter.count_inputs))


def test_operation_token_counter_is_not_revalidated_by_chunking_stages(
    monkeypatch,
) -> None:
    import server.app.services.chunking.tokenizer as tokenizer
    from server.app.services.chunking.service import _OperationTokenCounter
    from server.app.services.chunking.tokenizer import require_token_counter

    delegate = require_token_counter(CountingCharacterTokenCounter())
    operation_counter = _OperationTokenCounter(delegate)
    signature_calls = 0
    original_signature = tokenizer.inspect.signature

    def count_signature(*args, **kwargs):
        nonlocal signature_calls
        signature_calls += 1
        return original_signature(*args, **kwargs)

    monkeypatch.setattr(tokenizer.inspect, "signature", count_signature)

    assert require_token_counter(operation_counter) is operation_counter
    assert signature_calls == 0
