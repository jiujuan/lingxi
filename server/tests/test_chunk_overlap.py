from __future__ import annotations

import copy
import pickle
from dataclasses import dataclass

import pytest

from server.app.services.chunking.contracts import AtomicBlock, BlockType
from server.app.services.chunking.policy import ChunkPolicy
from server.app.services.chunking.recursive_splitter import (
    RecursiveSplitResult,
    SplitBlock,
    SplitReason,
)
from server.app.services.chunking.tokenizer import LocalTokenCounter
from server.app.services.chunking.overlap import (
    OverlapBlock,
    OverlapResult,
    apply_prose_overlap,
)


@dataclass(frozen=True)
class CharacterTokenCounter:
    name: str = "unicode-codepoint-fixture"
    version: str = "1.0"

    def count(self, text: str) -> int:
        return len(text)

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        return [text[index : index + limit] for index in range(0, len(text), limit)]


class CountingLocalTokenCounter:
    name = LocalTokenCounter.name
    version = LocalTokenCounter.version

    def __init__(self) -> None:
        self._delegate = LocalTokenCounter()
        self.count_calls = 0
        self.split_calls = 0

    def reset(self) -> None:
        self.count_calls = 0
        self.split_calls = 0

    def count(self, text: str) -> int:
        self.count_calls += 1
        return self._delegate.count(text)

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        self.split_calls += 1
        return self._delegate.split_by_token_limit(text, limit)


def policy(
    *,
    counter: object | None = None,
    min_tokens: int = 9,
    target_tokens: int = 14,
    max_tokens: int = 20,
    overlap_tokens: int = 8,
) -> ChunkPolicy:
    tokenizer = counter or CharacterTokenCounter()
    return ChunkPolicy(
        tokenizer_name=tokenizer.name,
        tokenizer_version=tokenizer.version,
        min_tokens=min_tokens,
        target_tokens=target_tokens,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
        parent_max_tokens=max_tokens * 2,
        embedding_provider_input_limit=max_tokens * 4,
    )


def split_block(
    source: str,
    start: int,
    end: int,
    *,
    counter: object | None = None,
    block_type: BlockType = BlockType.TEXT,
    split_reason: SplitReason = SplitReason.SENTENCE,
    index: int = 1,
    source_id: str = "source-1",
) -> SplitBlock:
    tokenizer = counter or CharacterTokenCounter()
    atomic = AtomicBlock(
        index=index,
        content=source,
        block_type=block_type,
        source_locator={"block": index, "source_unit": source_id},
        page_no=1,
        title_path=("Section",),
        structural_id=f"block-{index}",
        parent_structural_id="section-1",
    )
    locator = {
        "block": index,
        "nested": {"span": [start, end]},
        "_lingxi_chunk_span": {
            "split_reason": split_reason.value,
            "merged_char_start": start,
            "merged_char_end": end,
            "atomic_char_start": start,
            "atomic_char_end": end,
        },
    }
    content = source[start:end]
    return SplitBlock(
        content=content,
        block_type=block_type,
        title_path=("Section",),
        token_count=tokenizer.count(content),
        page_start=1,
        page_end=1,
        source_locators=(locator,),
        atomic_block_indexes=(index,),
        atomic_blocks=(atomic,),
        split_reason=split_reason,
        relative_char_start=start,
        relative_char_end=end,
    )


def result(*blocks: SplitBlock, split_count: int | None = None) -> RecursiveSplitResult:
    return RecursiveSplitResult(
        blocks=blocks,
        split_count=len(blocks) - 1 if split_count is None else split_count,
    )


def test_prefers_the_largest_complete_trailing_sentence_that_fits() -> None:
    source = "第一句完整。第二句完整。第三句正文。"
    boundary = source.index("第三")
    previous = split_block(source, 0, boundary)
    current = split_block(source, boundary, len(source))

    overlapped = apply_prose_overlap(
        result(previous, current),
        policy(overlap_tokens=8),
        CharacterTokenCounter(),
    )

    assert overlapped.blocks[0].overlap_prefix == ""
    assert overlapped.blocks[1].overlap_prefix == "第二句完整。"
    assert overlapped.blocks[1].content == "第二句完整。\n\n第三句正文。"
    assert overlapped.blocks[1].overlap_prefix_tokens == 6


def test_prefix_never_exceeds_overlap_budget_and_long_sentence_uses_hard_suffix() -> None:
    source = "abcdefghij" + "klmnop"
    previous = split_block(source, 0, 10, split_reason=SplitReason.TOKEN_HARD_CUT)
    current = split_block(source, 10, len(source), split_reason=SplitReason.TOKEN_HARD_CUT)
    counter = CharacterTokenCounter()

    overlapped = apply_prose_overlap(
        result(previous, current),
        policy(overlap_tokens=4),
        counter,
    )

    candidate = overlapped.blocks[1]
    assert candidate.overlap_prefix == "ghij"
    assert candidate.overlap_prefix_tokens == 4
    assert counter.count(candidate.overlap_prefix) <= 4


def test_prefix_is_shortened_until_total_child_is_within_max_tokens() -> None:
    source = "abcdefghij" + "klmnopqr"
    previous = split_block(source, 0, 10, split_reason=SplitReason.TOKEN_HARD_CUT)
    current = split_block(source, 10, len(source), split_reason=SplitReason.TOKEN_HARD_CUT)
    counter = CharacterTokenCounter()

    overlapped = apply_prose_overlap(
        result(previous, current),
        policy(
            min_tokens=6,
            target_tokens=9,
            max_tokens=12,
            overlap_tokens=5,
        ),
        counter,
    )

    candidate = overlapped.blocks[1]
    assert candidate.overlap_prefix == "ij"
    assert candidate.content == "ij\n\nklmnopqr"
    assert candidate.token_count == 12
    assert candidate.token_count <= 12


def test_adjacent_natural_paragraphs_do_not_receive_overlap() -> None:
    source = "第一自然段。\n\n第二自然段。"
    boundary = source.index("第二")
    previous = split_block(
        source,
        0,
        boundary - 2,
        split_reason=SplitReason.DOUBLE_NEWLINE,
    )
    current = split_block(
        source,
        boundary,
        len(source),
        split_reason=SplitReason.DOUBLE_NEWLINE,
    )

    overlapped = apply_prose_overlap(
        result(previous, current),
        policy(),
        CharacterTokenCounter(),
    )

    assert [block.overlap_prefix for block in overlapped.blocks] == ["", ""]
    assert [block.content for block in overlapped.blocks] == [
        previous.content,
        current.content,
    ]

def test_unsplit_natural_block_does_not_receive_overlap() -> None:
    source = "独立自然段。"
    independent = split_block(
        source,
        0,
        len(source),
        split_reason=SplitReason.UNSPLIT,
    )

    overlapped = apply_prose_overlap(
        result(independent, split_count=0),
        policy(),
        CharacterTokenCounter(),
    )

    assert len(overlapped.blocks) == 1
    assert overlapped.blocks[0].content == source
    assert overlapped.blocks[0].overlap_prefix == ""
    assert overlapped.blocks[0].overlap_prefix_tokens == 0


@pytest.mark.parametrize(
    "block_type",
    [
        BlockType.TABLE,
        BlockType.CODE,
        BlockType.IMAGE,
        BlockType.FORMULA,
        BlockType.LIST,
        BlockType.QUOTE,
    ],
)
def test_non_plain_prose_types_never_receive_generic_overlap(
    block_type: BlockType,
) -> None:
    source = "前一部分。后一部分。"
    boundary = source.index("后")
    previous = split_block(source, 0, boundary, block_type=block_type)
    current = split_block(source, boundary, len(source), block_type=block_type)

    overlapped = apply_prose_overlap(
        result(previous, current),
        policy(),
        CharacterTokenCounter(),
    )

    assert [block.overlap_prefix for block in overlapped.blocks] == ["", ""]
    assert [block.content for block in overlapped.blocks] == [
        previous.content,
        current.content,
    ]


def test_overlap_metadata_has_exact_source_span_without_expanding_unique_evidence() -> None:
    source = "甲句。乙句。丙句。"
    boundary = source.index("丙")
    previous = split_block(source, 0, boundary)
    current = split_block(source, boundary, len(source))
    original_locators = current.source_locators

    overlapped = apply_prose_overlap(
        result(previous, current),
        policy(overlap_tokens=5),
        CharacterTokenCounter(),
    )

    candidate = overlapped.blocks[1]
    prefix_start = source.index("乙")
    assert candidate.metadata["overlap"] == {
        "prefix_token_count": 3,
        "source_relative_char_start": prefix_start,
        "source_relative_char_end": boundary,
    }
    assert candidate.overlap_source_char_start == prefix_start
    assert candidate.overlap_source_char_end == boundary
    assert candidate.unique_content == current.content
    assert (candidate.relative_char_start, candidate.relative_char_end) == (
        current.relative_char_start,
        current.relative_char_end,
    )
    assert candidate.source_locators == original_locators
    assert candidate.atomic_block_indexes == current.atomic_block_indexes


def test_first_block_has_no_prefix_and_results_are_deterministic_and_immutable() -> None:
    source = "第一句。第二句。第三句。"
    second = source.index("第二")
    third = source.index("第三")
    input_result = result(
        split_block(source, 0, second),
        split_block(source, second, third),
        split_block(source, third, len(source)),
    )
    counter = CharacterTokenCounter()
    chunk_policy = policy(overlap_tokens=5)

    first = apply_prose_overlap(input_result, chunk_policy, counter)
    second_run = apply_prose_overlap(input_result, chunk_policy, counter)

    assert first == second_run
    assert isinstance(first, OverlapResult)
    assert isinstance(first.blocks[0], OverlapBlock)
    assert first.blocks[0].overlap_prefix == ""
    assert first.blocks[0].metadata == {}
    assert isinstance(first.blocks, tuple)
    assert copy.deepcopy(first) == first
    assert pickle.loads(pickle.dumps(first)) == first
    with pytest.raises((TypeError, AttributeError)):
        first.blocks[1].metadata["overlap"]["prefix_token_count"] = 999  # type: ignore[index]


def test_real_bpe_counter_keeps_prefix_and_total_within_true_token_budgets() -> None:
    counter = LocalTokenCounter()
    source = "Alpha first sentence. Beta second sentence. Gamma final payload."
    boundary = source.index("Gamma")
    previous = split_block(source, 0, boundary, counter=counter)
    current = split_block(source, boundary, len(source), counter=counter)
    chunk_policy = policy(
        counter=counter,
        min_tokens=8,
        target_tokens=10,
        max_tokens=12,
        overlap_tokens=7,
    )

    overlapped = apply_prose_overlap(
        result(previous, current),
        chunk_policy,
        counter,
    )

    candidate = overlapped.blocks[1]
    assert candidate.overlap_prefix == "Beta second sentence."
    assert candidate.overlap_prefix_tokens == counter.count(
        candidate.overlap_prefix
    )
    assert candidate.overlap_prefix_tokens <= chunk_policy.overlap_tokens
    assert candidate.token_count == counter.count(candidate.content)
    assert candidate.token_count <= chunk_policy.max_tokens
    assert source[
        candidate.overlap_source_char_start : candidate.overlap_source_char_end
    ] == candidate.overlap_prefix


def test_public_chunking_package_exports_overlap_api() -> None:
    import server.app.services.chunking as chunking

    assert chunking.OverlapBlock is OverlapBlock
    assert chunking.OverlapResult is OverlapResult
    assert chunking.apply_prose_overlap is apply_prose_overlap


def test_long_default_budget_hard_suffix_uses_bounded_tokenizer_calls() -> None:
    delegate = LocalTokenCounter()
    long_no_punctuation = "abcdefghij" * 1200
    previous_content = delegate.split_by_token_limit(
        long_no_punctuation,
        800,
    )[0]
    assert 700 <= delegate.count(previous_content) <= 800

    current_content = "tail payload"
    source = previous_content + current_content
    counter = CountingLocalTokenCounter()
    previous = split_block(
        source,
        0,
        len(previous_content),
        counter=counter,
        split_reason=SplitReason.TOKEN_HARD_CUT,
    )
    current = split_block(
        source,
        len(previous_content),
        len(source),
        counter=counter,
        split_reason=SplitReason.TOKEN_HARD_CUT,
    )
    chunk_policy = policy(
        counter=counter,
        min_tokens=100,
        target_tokens=450,
        max_tokens=800,
        overlap_tokens=64,
    )
    counter.reset()

    overlapped = apply_prose_overlap(
        result(previous, current),
        chunk_policy,
        counter,
    )

    candidate = overlapped.blocks[1]
    assert candidate.overlap_prefix
    assert candidate.overlap_prefix_tokens <= 64
    assert candidate.token_count <= 800
    assert counter.split_calls <= 2
    assert counter.count_calls <= 1024


@pytest.mark.parametrize(
    ("current_index", "current_source_id"),
    [(2, "source-1"), (1, "source-2")],
)
def test_adjacent_ranges_with_different_source_provenance_do_not_overlap(
    current_index: int,
    current_source_id: str,
) -> None:
    source = "前一来源尾句。后一来源正文。"
    boundary = source.index("后")
    previous = split_block(
        source,
        0,
        boundary,
        index=1,
        source_id="source-1",
    )
    current = split_block(
        source,
        boundary,
        len(source),
        index=current_index,
        source_id=current_source_id,
    )

    overlapped = apply_prose_overlap(
        result(previous, current),
        policy(),
        CharacterTokenCounter(),
    )

    assert overlapped.blocks[1].overlap_prefix == ""
    assert overlapped.blocks[1].content == current.content


def _rebuild_overlap_block(
    block: OverlapBlock,
    *,
    metadata: dict[str, object],
) -> OverlapBlock:
    return OverlapBlock(
        content=block.content,
        unique_content=block.unique_content,
        block_type=block.block_type,
        title_path=block.title_path,
        token_count=block.token_count,
        page_start=block.page_start,
        page_end=block.page_end,
        source_locators=block.source_locators,
        atomic_block_indexes=block.atomic_block_indexes,
        atomic_blocks=block.atomic_blocks,
        split_reason=block.split_reason,
        relative_char_start=block.relative_char_start,
        relative_char_end=block.relative_char_end,
        overlap_prefix=block.overlap_prefix,
        overlap_prefix_tokens=block.overlap_prefix_tokens,
        overlap_source_char_start=block.overlap_source_char_start,
        overlap_source_char_end=block.overlap_source_char_end,
        metadata=metadata,
    )


@pytest.mark.parametrize(
    "invalid_overlap_metadata",
    [
        None,
        {},
        {
            "prefix_token_count": 999,
            "source_relative_char_start": 0,
            "source_relative_char_end": 1,
        },
    ],
)
def test_direct_construction_rejects_overlap_metadata_that_conflicts_with_typed_fields(
    invalid_overlap_metadata: object,
) -> None:
    source = "甲句。乙句。丙句。"
    boundary = source.index("丙")
    generated = apply_prose_overlap(
        result(
            split_block(source, 0, boundary),
            split_block(source, boundary, len(source)),
        ),
        policy(overlap_tokens=5),
        CharacterTokenCounter(),
    ).blocks[1]

    with pytest.raises(ValueError, match="overlap metadata"):
        _rebuild_overlap_block(
            generated,
            metadata={"overlap": invalid_overlap_metadata},
        )


def test_direct_construction_derives_overlap_metadata_from_typed_fields() -> None:
    source = "甲句。乙句。丙句。"
    boundary = source.index("丙")
    generated = apply_prose_overlap(
        result(
            split_block(source, 0, boundary),
            split_block(source, boundary, len(source)),
        ),
        policy(overlap_tokens=5),
        CharacterTokenCounter(),
    ).blocks[1]

    rebuilt = _rebuild_overlap_block(generated, metadata={})
    restored = pickle.loads(pickle.dumps(rebuilt))

    expected = {
        "prefix_token_count": rebuilt.overlap_prefix_tokens,
        "source_relative_char_start": rebuilt.overlap_source_char_start,
        "source_relative_char_end": rebuilt.overlap_source_char_end,
    }
    assert rebuilt.metadata["overlap"] == expected
    assert restored.metadata["overlap"] == expected
    assert restored == rebuilt
