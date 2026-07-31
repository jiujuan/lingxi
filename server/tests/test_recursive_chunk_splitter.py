from __future__ import annotations

import copy
import pickle
from dataclasses import dataclass

import pytest

from server.app.services.chunking.contracts import AtomicBlock, BlockType
from server.app.services.chunking.merge import MergedBlock
from server.app.services.chunking.policy import ChunkPolicy
from server.app.services.chunking.recursive_splitter import (
    ChunkSplitNoProgressError,
    RecursiveSplitResult,
    SplitBlock,
    SplitReason,
    split_oversized_prose,
)
from server.app.services.chunking.tokenizer import LocalTokenCounter


@dataclass(frozen=True)
class CharacterTokenCounter:
    """Deterministic fixture: one Unicode code point is one token."""

    name: str = "unicode-codepoint-fixture"
    version: str = "1.0"

    def count(self, text: str) -> int:
        return len(text)

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        return [text[index : index + limit] for index in range(0, len(text), limit)]


@dataclass(frozen=True)
class NoProgressTokenCounter(CharacterTokenCounter):
    name: str = "no-progress-fixture"

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        return [text]


class CountingLocalTokenCounter:
    name = LocalTokenCounter.name
    version = LocalTokenCounter.version

    def __init__(self) -> None:
        self._delegate = LocalTokenCounter()
        self.split_limits: list[int] = []
        self.split_input_token_counts: list[int] = []

    def count(self, text: str) -> int:
        return self._delegate.count(text)

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        self.split_limits.append(limit)
        self.split_input_token_counts.append(self._delegate.count(text))
        return self._delegate.split_by_token_limit(text, limit)


def policy(
    *,
    min_tokens: int = 4,
    target_tokens: int = 8,
    max_tokens: int = 10,
) -> ChunkPolicy:
    return ChunkPolicy(
        tokenizer_name="unicode-codepoint-fixture",
        tokenizer_version="1.0",
        min_tokens=min_tokens,
        target_tokens=target_tokens,
        max_tokens=max_tokens,
        overlap_tokens=min(2, min_tokens - 1),
        parent_max_tokens=max_tokens * 2,
        embedding_provider_input_limit=max_tokens * 4,
    )


def atomic(
    index: int,
    content: str,
    *,
    page_no: int = 1,
    locator: dict[str, object] | None = None,
) -> AtomicBlock:
    return AtomicBlock(
        index=index,
        content=content,
        block_type=BlockType.TEXT,
        source_locator=locator or {"block": index, "page": page_no},
        page_no=page_no,
        title_path=("Section",),
        structural_id=f"block-{index}",
        parent_structural_id="section-1",
    )


def merged(*blocks: AtomicBlock) -> MergedBlock:
    content_parts = [blocks[0].content]
    for current in blocks[1:]:
        content_parts.extend(("\n\n", current.content))
    content = "".join(content_parts)
    counter = CharacterTokenCounter()
    pages = [block.page_no for block in blocks]
    return MergedBlock(
        content=content,
        block_type=BlockType.TEXT,
        title_path=("Section",),
        token_count=counter.count(content),
        page_start=min(pages),
        page_end=max(pages),
        source_locators=tuple(block.source_locator for block in blocks),
        atomic_block_indexes=tuple(block.index for block in blocks),
        atomic_blocks=blocks,
    )


def split(
    block: MergedBlock,
    *,
    split_policy: ChunkPolicy | None = None,
    counter: object | None = None,
) -> RecursiveSplitResult:
    return split_oversized_prose(
        block,
        split_policy or policy(),
        counter or CharacterTokenCounter(),
    )


def assert_valid_ranges(source: str, result: RecursiveSplitResult) -> None:
    previous_start = -1
    for candidate in result.blocks:
        assert candidate.content
        assert candidate.content == source[
            candidate.relative_char_start : candidate.relative_char_end
        ]
        assert 0 <= candidate.relative_char_start < candidate.relative_char_end <= len(
            source
        )
        assert candidate.relative_char_start > previous_start
        previous_start = candidate.relative_char_start


def test_structure_subblocks_are_used_before_textual_separators() -> None:
    source = merged(
        atomic(1, "甲甲。乙乙"),
        atomic(2, "丙丙。丁丁", page_no=2),
    )

    result = split(source, split_policy=policy(max_tokens=7, target_tokens=6))

    assert [candidate.content for candidate in result.blocks] == [
        "甲甲。乙乙",
        "丙丙。丁丁",
    ]
    assert [candidate.split_reason for candidate in result.blocks] == [
        SplitReason.STRUCTURAL_BLOCK,
        SplitReason.STRUCTURAL_BLOCK,
    ]
    assert [candidate.atomic_block_indexes for candidate in result.blocks] == [
        (1,),
        (2,),
    ]


def test_double_newline_is_preferred_over_sentence_boundaries() -> None:
    source = merged(atomic(1, "甲乙。丙丁\n\n戊己。庚辛"))

    result = split(source, split_policy=policy(max_tokens=7, target_tokens=7))

    assert [candidate.content for candidate in result.blocks] == [
        "甲乙。丙丁",
        "戊己。庚辛",
    ]
    assert {candidate.split_reason for candidate in result.blocks} == {
        SplitReason.DOUBLE_NEWLINE
    }


def test_single_newline_precedes_sentence_fallback() -> None:
    source = merged(atomic(1, "甲乙。丙丁\n戊己。庚辛"))

    result = split(source, split_policy=policy(max_tokens=7, target_tokens=7))

    assert [candidate.content for candidate in result.blocks] == [
        "甲乙。丙丁",
        "戊己。庚辛",
    ]
    assert {candidate.split_reason for candidate in result.blocks} == {
        SplitReason.SINGLE_NEWLINE
    }


def test_chinese_and_english_sentence_endings_are_used_before_whitespace() -> None:
    source = merged(atomic(1, "甲乙丙丁。戊己庚辛！Alpha beta?Gamma delta."))

    result = split(source, split_policy=policy(max_tokens=12, target_tokens=10))

    joined_without_spaces = "".join(
        candidate.content for candidate in result.blocks
    ).replace(" ", "")
    assert joined_without_spaces == (
        source.content.replace(" ", "")
    )
    assert all(candidate.token_count <= 12 for candidate in result.blocks)
    assert SplitReason.SENTENCE in {
        candidate.split_reason for candidate in result.blocks
    }
    assert SplitReason.PUNCTUATION_OR_WHITESPACE not in {
        candidate.split_reason for candidate in result.blocks
    }


def test_punctuation_and_whitespace_precede_token_hard_cut() -> None:
    source = merged(atomic(1, "alpha beta,gamma delta,epsilon zeta"))

    result = split(source, split_policy=policy(max_tokens=12, target_tokens=10))

    assert all(candidate.token_count <= 12 for candidate in result.blocks)
    assert {candidate.split_reason for candidate in result.blocks} == {
        SplitReason.PUNCTUATION_OR_WHITESPACE
    }


def test_unseparated_long_text_terminates_with_token_hard_cut() -> None:
    source = merged(atomic(1, "甲" * 27))

    result = split(source)

    assert "".join(candidate.content for candidate in result.blocks) == source.content
    assert all(candidate.token_count <= 10 for candidate in result.blocks)
    assert all(
        candidate.split_reason is SplitReason.TOKEN_HARD_CUT
        for candidate in result.blocks
    )
    assert result.split_count == len(result.blocks) - 1


def test_empty_segments_are_removed_without_emitting_empty_chunks() -> None:
    source = merged(atomic(1, "甲乙\n\n\n\n丙丁\n\n\n\n戊己"))

    result = split(source, split_policy=policy(max_tokens=6, target_tokens=5))

    assert all(candidate.content.strip() for candidate in result.blocks)
    assert [candidate.content.strip() for candidate in result.blocks] == [
        "甲乙",
        "丙丁",
        "戊己",
    ]


def test_tiny_hard_cut_tail_is_rebalanced_without_exceeding_max() -> None:
    source = merged(atomic(1, "甲" * 25))

    result = split(
        source,
        split_policy=policy(min_tokens=6, target_tokens=8, max_tokens=10),
    )

    counts = [candidate.token_count for candidate in result.blocks]
    assert counts == [10, 8, 7]
    assert all(6 <= count <= 10 for count in counts)
    assert "".join(candidate.content for candidate in result.blocks) == source.content


def assert_locator_reasons_match_blocks(result: RecursiveSplitResult) -> None:
    for candidate in result.blocks:
        for locator in candidate.source_locators:
            assert (
                locator["_lingxi_chunk_span"]["split_reason"]
                == candidate.split_reason.value
            )


def test_sentence_tiny_tail_uses_hard_cut_without_natural_boundary() -> None:
    source = merged(atomic(1, "abcdefghi.XYZ?"))

    result = split(
        source,
        split_policy=policy(min_tokens=6, target_tokens=8, max_tokens=10),
    )

    assert [candidate.content for candidate in result.blocks] == [
        "abcdefgh",
        "i.XYZ?",
    ]
    assert [candidate.split_reason for candidate in result.blocks] == [
        SplitReason.TOKEN_HARD_CUT,
        SplitReason.TOKEN_HARD_CUT,
    ]
    assert [
        (candidate.relative_char_start, candidate.relative_char_end)
        for candidate in result.blocks
    ] == [(0, 8), (8, 14)]
    assert_valid_ranges(source.content, result)
    assert_locator_reasons_match_blocks(result)


def test_newline_tiny_tail_rebalances_at_real_sentence_boundary() -> None:
    source = merged(atomic(1, "abcdef.gh\nXYZ?"))

    result = split(
        source,
        split_policy=policy(min_tokens=6, target_tokens=8, max_tokens=10),
    )

    assert [candidate.content for candidate in result.blocks] == [
        "abcdef.",
        "gh\nXYZ?",
    ]
    assert [candidate.split_reason for candidate in result.blocks] == [
        SplitReason.SENTENCE,
        SplitReason.SENTENCE,
    ]
    assert [candidate.token_count for candidate in result.blocks] == [7, 7]
    assert_valid_ranges(source.content, result)
    assert_locator_reasons_match_blocks(result)


def test_structure_tail_uses_real_punctuation_boundary() -> None:
    source = merged(
        atomic(1, "abcdef gh"),
        atomic(2, "XYZ?", page_no=2),
    )

    result = split(
        source,
        split_policy=policy(min_tokens=6, target_tokens=8, max_tokens=10),
    )

    assert [candidate.content for candidate in result.blocks] == [
        "abcdef",
        "gh\n\nXYZ?",
    ]
    assert [candidate.split_reason for candidate in result.blocks] == [
        SplitReason.PUNCTUATION_OR_WHITESPACE,
        SplitReason.PUNCTUATION_OR_WHITESPACE,
    ]
    assert [candidate.atomic_block_indexes for candidate in result.blocks] == [
        (1,),
        (1, 2),
    ]
    assert_valid_ranges(source.content, result)
    assert_locator_reasons_match_blocks(result)


def test_structure_tiny_tail_uses_hard_cut_when_no_natural_boundary_fits() -> None:
    source = merged(
        atomic(1, "abcdefghij"),
        atomic(2, "XYZ?", page_no=2),
    )

    result = split(
        source,
        split_policy=policy(min_tokens=6, target_tokens=8, max_tokens=10),
    )

    assert [candidate.content for candidate in result.blocks] == [
        "abcdefgh",
        "ij\n\nXYZ?",
    ]
    assert [candidate.split_reason for candidate in result.blocks] == [
        SplitReason.TOKEN_HARD_CUT,
        SplitReason.TOKEN_HARD_CUT,
    ]
    assert all(candidate.token_count <= 10 for candidate in result.blocks)
    assert_valid_ranges(source.content, result)
    assert_locator_reasons_match_blocks(result)


def test_local_bpe_non_monotonic_prefix_counts_keep_exact_char_spans() -> None:
    counter = LocalTokenCounter()
    source = merged(atomic(1, "eisbn"))
    local_policy = ChunkPolicy(
        tokenizer_name=counter.name,
        tokenizer_version=counter.version,
        min_tokens=1,
        target_tokens=1,
        max_tokens=1,
        overlap_tokens=0,
        parent_max_tokens=2,
        embedding_provider_input_limit=4,
    )

    result = split(source, split_policy=local_policy, counter=counter)

    assert [candidate.content for candidate in result.blocks] == ["ei", "sb", "n"]
    assert [candidate.token_count for candidate in result.blocks] == [1, 1, 1]
    assert [
        (candidate.relative_char_start, candidate.relative_char_end)
        for candidate in result.blocks
    ] == [(0, 2), (2, 4), (4, 5)]
    assert_valid_ranges(source.content, result)
    locator_ranges = []
    for candidate in result.blocks:
        assert not hasattr(candidate, "relative_token_start")
        assert not hasattr(candidate, "relative_token_end")
        for locator in candidate.source_locators:
            span = locator["_lingxi_chunk_span"]
            assert not any("token" in key for key in span)
            locator_ranges.append(
                (
                    span["merged_char_start"],
                    span["merged_char_end"],
                    span["atomic_char_start"],
                    span["atomic_char_end"],
                )
            )
    assert locator_ranges == [
        (0, 2, 0, 2),
        (2, 4, 2, 4),
        (4, 5, 4, 5),
    ]


def test_local_hard_tail_rebalance_has_constant_split_call_budget() -> None:
    counter = CountingLocalTokenCounter()
    text = "中" * 850
    source = merged(atomic(1, text))
    default_policy = ChunkPolicy(
        tokenizer_name=counter.name,
        tokenizer_version=counter.version,
    )
    assert counter.count(text) == 850

    result = split(source, split_policy=default_policy, counter=counter)

    assert [candidate.token_count for candidate in result.blocks] == [450, 400]
    assert all(
        candidate.token_count <= default_policy.max_tokens
        for candidate in result.blocks
    )
    assert "".join(candidate.content for candidate in result.blocks) == text
    assert [candidate.split_reason for candidate in result.blocks] == [
        SplitReason.TOKEN_HARD_CUT,
        SplitReason.TOKEN_HARD_CUT,
    ]
    assert counter.split_limits == [
        default_policy.max_tokens,
        default_policy.target_tokens,
    ]
    assert counter.split_input_token_counts == [850, 850]
    assert sum(counter.split_input_token_counts) == 1_700


def test_unicode_relative_spans_use_python_code_point_indexes() -> None:
    text = "甲乙。🙂丙丁。戊己庚辛"
    source = merged(
        atomic(
            7,
            text,
            locator={"page": 3, "bbox": [1, 2, 3, 4]},
            page_no=3,
        )
    )

    result = split(source, split_policy=policy(max_tokens=6, target_tokens=6))

    assert_valid_ranges(text, result)
    emoji_chunk = next(
        candidate for candidate in result.blocks if "🙂" in candidate.content
    )
    assert emoji_chunk.content[emoji_chunk.content.index("🙂")] == text[
        emoji_chunk.relative_char_start + emoji_chunk.content.index("🙂")
    ]
    assert emoji_chunk.token_count == len(emoji_chunk.content)
    assert not hasattr(emoji_chunk, "relative_token_start")
    assert not hasattr(emoji_chunk, "relative_token_end")


def test_split_reason_ranges_and_provenance_are_preserved_in_locators() -> None:
    first_locator = {"page": 1, "span": {"line": 3}}
    second_locator = {"page": 2, "span": {"line": 8}}
    source = merged(
        atomic(1, "甲" * 8, locator=first_locator),
        atomic(2, "乙" * 14, page_no=2, locator=second_locator),
    )

    result = split(source, split_policy=policy(max_tokens=8, target_tokens=8))

    assert [candidate.atomic_block_indexes for candidate in result.blocks] == [
        (1,),
        (2,),
        (2,),
    ]
    for candidate in result.blocks:
        assert candidate.source_locators
        for locator in candidate.source_locators:
            assert locator["page"] in (1, 2)
            span = locator["_lingxi_chunk_span"]
            assert span["split_reason"] == candidate.split_reason.value
            assert span["merged_char_start"] >= candidate.relative_char_start
            assert span["merged_char_end"] <= candidate.relative_char_end
            assert span["atomic_char_start"] < span["atomic_char_end"]
            assert not {
                "merged_token_start",
                "merged_token_end",
                "atomic_token_start",
                "atomic_token_end",
            }.intersection(span)
    assert first_locator == {"page": 1, "span": {"line": 3}}
    assert second_locator == {"page": 2, "span": {"line": 8}}


def test_same_input_produces_equal_immutable_pickleable_results() -> None:
    source = merged(atomic(1, "甲乙。丙丁。戊己。庚辛。壬癸。"))

    first = split(source, split_policy=policy(max_tokens=6, target_tokens=6))
    second = split(source, split_policy=policy(max_tokens=6, target_tokens=6))

    assert first == second
    assert copy.deepcopy(first) == first
    assert pickle.loads(pickle.dumps(first)) == first
    with pytest.raises(TypeError):
        first.blocks[0].source_locators[0]["page"] = 99  # type: ignore[index]


def test_non_oversized_prose_is_returned_as_one_unsplit_block() -> None:
    source = merged(atomic(1, "短文本"))

    result = split(source)

    assert len(result.blocks) == 1
    assert result.blocks[0].content == source.content
    assert result.blocks[0].split_reason is SplitReason.UNSPLIT
    assert result.split_count == 0


def test_no_progress_hard_split_raises_structured_non_retryable_error() -> None:
    source = merged(atomic(1, "甲" * 20))

    with pytest.raises(ChunkSplitNoProgressError) as exc_info:
        split(source, counter=NoProgressTokenCounter())

    error = exc_info.value
    assert error.code == "CHUNK_SPLIT_NO_PROGRESS"
    assert error.retryable is False
    assert error.block_hash
    assert error.block_hash in str(error)


def test_split_block_rejects_unaligned_public_provenance() -> None:
    source_block = atomic(1, "甲乙")

    with pytest.raises(ValueError, match="aligned"):
        SplitBlock(
            content="甲乙",
            block_type=BlockType.TEXT,
            title_path=("Section",),
            token_count=2,
            page_start=1,
            page_end=1,
            source_locators=(
                {"block": 1, "_lingxi_chunk_span": {"split_reason": "unsplit"}},
                {"block": 99, "_lingxi_chunk_span": {"split_reason": "unsplit"}},
            ),
            atomic_block_indexes=(1,),
            atomic_blocks=(source_block,),
            split_reason=SplitReason.UNSPLIT,
            relative_char_start=0,
            relative_char_end=2,
        )


def test_package_exports_recursive_splitter_public_api() -> None:
    from server.app.services import chunking

    assert chunking.SplitReason is SplitReason
    assert chunking.RecursiveSplitResult is RecursiveSplitResult
    assert chunking.split_oversized_prose is split_oversized_prose
