from __future__ import annotations

import copy
import pickle
from collections.abc import Mapping
from dataclasses import dataclass

import pytest

from server.app.services.chunking.contracts import (
    AtomicBlock,
    BlockType,
    ChunkingWarning,
)
from server.app.services.chunking.merge import (
    MergedBlock,
    MergeResult,
    group_by_safe_boundary,
    merge_small_blocks,
)
from server.app.services.chunking.policy import ChunkPolicy


@dataclass(frozen=True)
class WordTokenCounter:
    name: str = "word-fixture"
    version: str = "1.0"

    def count(self, text: str) -> int:
        return len(text.split())

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        words = text.split()
        return [
            " ".join(words[index : index + limit])
            for index in range(0, len(words), limit)
        ]


def block(
    index: int,
    content: str,
    *,
    block_type: BlockType = BlockType.TEXT,
    title_path: tuple[str, ...] = ("Section",),
    page_no: int | None = 1,
    parent_structural_id: str | None = "section-1",
    metadata: dict[str, object] | None = None,
) -> AtomicBlock:
    return AtomicBlock(
        index=index,
        content=content,
        block_type=block_type,
        source_locator={"block": index, "page": page_no},
        page_no=page_no,
        title_path=title_path,
        structural_id=f"block-{index}",
        parent_structural_id=parent_structural_id,
        metadata=metadata or {},
    )


def policy(*, allow_cross_page_merge: bool = True) -> ChunkPolicy:
    return ChunkPolicy(
        tokenizer_name="word-fixture",
        tokenizer_version="1.0",
        min_tokens=4,
        target_tokens=6,
        max_tokens=8,
        overlap_tokens=1,
        parent_max_tokens=16,
        embedding_provider_input_limit=32,
        allow_cross_page_merge=allow_cross_page_merge,
    )


def test_group_by_safe_boundary_sorts_and_keeps_cross_page_prose_together() -> None:
    blocks = [
        block(2, "gamma delta", page_no=2),
        block(1, "alpha beta", page_no=1),
    ]

    groups = group_by_safe_boundary(blocks, policy())

    assert tuple(item.index for item in groups[0]) == (1, 2)
    assert len(groups) == 1


def test_group_by_safe_boundary_splits_title_parent_page_and_hard_boundary() -> None:
    blocks = [
        block(1, "one", title_path=("A",), parent_structural_id="p1"),
        block(2, "two", title_path=("B",), parent_structural_id="p1"),
        block(3, "three", title_path=("B",), parent_structural_id="p2"),
        block(4, "four", title_path=("B",), parent_structural_id="p2", page_no=2),
        block(
            5,
            "hard",
            title_path=("B",),
            parent_structural_id="p2",
            page_no=2,
            metadata={"hard_boundary": True},
        ),
        block(6, "after", title_path=("B",), parent_structural_id="p2", page_no=2),
    ]

    groups = group_by_safe_boundary(
        blocks,
        policy(allow_cross_page_merge=False),
    )

    assert [tuple(item.index for item in group) for group in groups] == [
        (1,),
        (2,),
        (3,),
        (4,),
        (5,),
        (6,),
    ]


@pytest.mark.parametrize(
    "strong_type",
    [BlockType.TABLE, BlockType.CODE, BlockType.IMAGE, BlockType.FORMULA],
)
def test_group_by_safe_boundary_isolates_strong_typed_blocks(
    strong_type: BlockType,
) -> None:
    blocks = [
        block(1, "before"),
        block(2, "typed payload", block_type=strong_type),
        block(3, "after"),
    ]

    groups = group_by_safe_boundary(blocks, policy())

    assert [tuple(item.index for item in group) for group in groups] == [
        (1,),
        (2,),
        (3,),
    ]


def test_merge_small_same_section_prose_preserves_full_provenance() -> None:
    blocks = [
        block(1, "alpha beta", page_no=1),
        block(2, "gamma delta", page_no=2),
    ]

    result = merge_small_blocks(blocks, policy(), WordTokenCounter())

    assert result.warnings == ()
    assert result.merge_count == 1
    assert result.blocks == (
        MergedBlock(
            content="alpha beta\n\ngamma delta",
            block_type=BlockType.TEXT,
            title_path=("Section",),
            token_count=4,
            page_start=1,
            page_end=2,
            source_locators=(
                {"block": 1, "page": 1},
                {"block": 2, "page": 2},
            ),
            atomic_block_indexes=(1, 2),
            atomic_blocks=tuple(blocks),
        ),
    )


def test_merge_does_not_cross_title_path_or_strong_type_boundaries() -> None:
    blocks = [
        block(1, "tiny", title_path=("A",)),
        block(2, "other", title_path=("B",)),
        block(3, "table payload", block_type=BlockType.TABLE, title_path=("B",)),
        block(4, "after", title_path=("B",)),
    ]

    result = merge_small_blocks(blocks, policy(), WordTokenCounter())

    assert [chunk.atomic_block_indexes for chunk in result.blocks] == [
        (1,),
        (2,),
        (3,),
        (4,),
    ]
    assert result.merge_count == 0
    assert [warning.code for warning in result.warnings] == [
        "TINY_CHUNK_UNMERGEABLE",
        "TINY_CHUNK_UNMERGEABLE",
        "TINY_CHUNK_UNMERGEABLE",
    ]


def test_list_and_quote_are_compatible_and_list_items_use_single_newline() -> None:
    blocks = [
        block(1, "- alpha", block_type=BlockType.LIST),
        block(2, "- beta", block_type=BlockType.LIST),
        block(3, "> context", block_type=BlockType.QUOTE),
    ]

    result = merge_small_blocks(blocks, policy(), WordTokenCounter())

    assert len(result.blocks) == 1
    assert result.blocks[0].content == "- alpha\n- beta\n\n> context"
    assert result.blocks[0].block_type is BlockType.TEXT
    assert result.blocks[0].atomic_block_indexes == (1, 2, 3)
    assert result.blocks[0].token_count == 6


def test_cross_page_merge_can_be_disabled() -> None:
    blocks = [
        block(1, "alpha beta", page_no=1),
        block(2, "gamma delta", page_no=2),
    ]

    result = merge_small_blocks(
        blocks,
        policy(allow_cross_page_merge=False),
        WordTokenCounter(),
    )

    assert [chunk.atomic_block_indexes for chunk in result.blocks] == [(1,), (2,)]
    assert [warning.code for warning in result.warnings] == [
        "TINY_CHUNK_UNMERGEABLE",
        "TINY_CHUNK_UNMERGEABLE",
    ]


def test_tiny_buffer_may_absorb_next_block_above_target_but_within_max() -> None:
    blocks = [
        block(1, "one two"),
        block(2, "three four five six seven"),
    ]

    result = merge_small_blocks(blocks, policy(), WordTokenCounter())

    assert [chunk.atomic_block_indexes for chunk in result.blocks] == [(1, 2)]
    assert result.blocks[0].token_count == 7
    assert result.blocks[0].token_count > policy().target_tokens
    assert result.blocks[0].token_count <= policy().max_tokens
    assert result.warnings == ()


def test_tiny_tail_merges_back_without_exceeding_max_tokens() -> None:
    blocks = [
        block(1, "one two three four five six"),
        block(2, "seven eight"),
    ]

    result = merge_small_blocks(blocks, policy(), WordTokenCounter())

    assert [chunk.atomic_block_indexes for chunk in result.blocks] == [(1, 2)]
    assert result.blocks[0].token_count == 8
    assert result.merge_count == 1
    assert result.warnings == ()


def test_tiny_tail_is_retained_with_warning_when_back_merge_would_exceed_max() -> None:
    blocks = [
        block(1, "one two three four five six seven"),
        block(2, "eight nine"),
    ]

    result = merge_small_blocks(blocks, policy(), WordTokenCounter())

    assert [chunk.atomic_block_indexes for chunk in result.blocks] == [(1,), (2,)]
    assert all(chunk.token_count <= policy().max_tokens for chunk in result.blocks)
    assert result.merge_count == 0
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.code == "TINY_CHUNK_UNMERGEABLE"
    assert warning.metadata["atomic_block_indexes"] == (2,)
    assert warning.metadata["token_count"] == 2


def test_tiny_middle_block_can_merge_back_when_forward_merge_exceeds_max() -> None:
    blocks = [
        block(1, "one two three four"),
        block(2, "five six"),
        block(3, "seven eight nine ten eleven twelve thirteen"),
    ]

    result = merge_small_blocks(blocks, policy(), WordTokenCounter())

    assert [chunk.atomic_block_indexes for chunk in result.blocks] == [(1, 2), (3,)]
    assert [chunk.token_count for chunk in result.blocks] == [6, 7]
    assert result.merge_count == 1
    assert result.warnings == ()


def test_empty_input_returns_empty_result() -> None:
    result = merge_small_blocks([], policy(), WordTokenCounter())

    assert result.blocks == ()
    assert result.warnings == ()
    assert result.merge_count == 0


def test_merge_api_is_exported_from_chunking_package() -> None:
    from server.app.services import chunking

    assert chunking.MergedBlock is MergedBlock
    assert chunking.group_by_safe_boundary is group_by_safe_boundary
    assert chunking.merge_small_blocks is merge_small_blocks


def _mutable_merged_block() -> tuple[MergedBlock, dict[str, object], list[object]]:
    locator: dict[str, object] = {
        "page": 1,
        "span": {"lines": [1, 2]},
    }
    atomic = AtomicBlock(
        index=1,
        content="alpha beta",
        block_type=BlockType.TEXT,
        source_locator=locator,
        page_no=1,
        title_path=("Section",),
        structural_id="block-1",
        parent_structural_id="section-1",
    )
    locators: list[object] = [locator]
    merged = MergedBlock(
        content="alpha beta",
        block_type=BlockType.TEXT,
        title_path=["Section"],  # type: ignore[arg-type]
        token_count=2,
        page_start=1,
        page_end=1,
        source_locators=locators,  # type: ignore[arg-type]
        atomic_block_indexes=[1],  # type: ignore[arg-type]
        atomic_blocks=[atomic],  # type: ignore[arg-type]
    )
    return merged, locator, locators


def test_merged_block_defensively_copies_and_recursively_freezes_locators() -> None:
    merged, locator, locators = _mutable_merged_block()

    locator["page"] = 99
    span = locator["span"]
    assert isinstance(span, dict)
    lines = span["lines"]
    assert isinstance(lines, list)
    lines.append(3)
    locators.append({"page": 2})

    assert merged.title_path == ("Section",)
    assert merged.atomic_block_indexes == (1,)
    assert isinstance(merged.atomic_blocks, tuple)
    assert len(merged.source_locators) == 1
    frozen_locator = merged.source_locators[0]
    assert frozen_locator["page"] == 1
    assert frozen_locator["span"]["lines"] == (1, 2)
    assert isinstance(frozen_locator, Mapping)
    assert not isinstance(frozen_locator, dict)
    with pytest.raises(TypeError):
        frozen_locator["page"] = 2  # type: ignore[index]


def test_merged_block_normalizes_all_sequence_inputs_defensively() -> None:
    locator = {"block": 1, "page": 1}
    atomic = AtomicBlock(
        index=1,
        content="alpha beta",
        block_type=BlockType.TEXT,
        source_locator=locator,
        page_no=1,
        title_path=("Section",),
    )
    title_path = ["Section"]
    locators = [locator]
    indexes = [1]
    atomic_blocks = [atomic]

    merged = MergedBlock(
        content="alpha beta",
        block_type=BlockType.TEXT,
        title_path=title_path,  # type: ignore[arg-type]
        token_count=2,
        page_start=1,
        page_end=1,
        source_locators=locators,  # type: ignore[arg-type]
        atomic_block_indexes=indexes,  # type: ignore[arg-type]
        atomic_blocks=atomic_blocks,  # type: ignore[arg-type]
    )
    title_path.append("mutated")
    locators.append({"block": 2, "page": 1})
    indexes.append(2)
    atomic_blocks.append(block(2, "mutated"))

    assert merged.title_path == ("Section",)
    assert len(merged.source_locators) == 1
    assert merged.atomic_block_indexes == (1,)
    assert merged.atomic_blocks == (atomic,)
    assert isinstance(merged.title_path, tuple)
    assert isinstance(merged.source_locators, tuple)
    assert isinstance(merged.atomic_block_indexes, tuple)
    assert isinstance(merged.atomic_blocks, tuple)


def test_merged_block_supports_copy_deepcopy_and_pickle_round_trip() -> None:
    merged, _, _ = _mutable_merged_block()

    shallow = copy.copy(merged)
    deep = copy.deepcopy(merged)
    restored = pickle.loads(pickle.dumps(merged))

    for candidate in (shallow, deep, restored):
        assert candidate == merged
        assert isinstance(candidate.source_locators, tuple)
        assert candidate.source_locators[0]["span"]["lines"] == (1, 2)
        assert not isinstance(candidate.source_locators[0], dict)


def test_merge_result_defensively_normalizes_lists_and_round_trips() -> None:
    merged, _, _ = _mutable_merged_block()
    warning = ChunkingWarning(code="TEST", message="test warning")
    blocks = [merged]
    warnings = [warning]

    result = MergeResult(
        blocks=blocks,  # type: ignore[arg-type]
        warnings=warnings,  # type: ignore[arg-type]
        merge_count=1,
    )
    blocks.clear()
    warnings.clear()

    assert result.blocks == (merged,)
    assert result.warnings == (warning,)
    assert isinstance(result.blocks, tuple)
    assert isinstance(result.warnings, tuple)
    assert copy.copy(result) == result
    assert copy.deepcopy(result) == result
    assert pickle.loads(pickle.dumps(result)) == result


@pytest.mark.parametrize(
    ("source_locators", "atomic_indexes"),
    [
        ([], [1]),
        ([{"page": 1}], []),
        ([{"page": 1}], [99]),
    ],
)
def test_merged_block_rejects_inconsistent_provenance_sequences(
    source_locators: list[dict[str, object]],
    atomic_indexes: list[int],
) -> None:
    atomic = block(1, "alpha beta")

    with pytest.raises(ValueError, match="provenance"):
        MergedBlock(
            content="alpha beta",
            block_type=BlockType.TEXT,
            title_path=atomic.title_path,
            token_count=2,
            page_start=1,
            page_end=1,
            source_locators=source_locators,  # type: ignore[arg-type]
            atomic_block_indexes=atomic_indexes,  # type: ignore[arg-type]
            atomic_blocks=(atomic,),
        )
