import copy
import json
import pickle
from collections.abc import Mapping
from dataclasses import FrozenInstanceError

import pytest

from server.app.integrations.parsers.base import ParsedBlock
from server.app.services.chunking import (
    AtomicBlock,
    BlockType,
    ChunkingResult,
    ChunkingStats,
    ChunkingWarning,
    ChunkLevel,
    NormalizedChunk,
    to_json_value,
)


def _chunk(
    local_id: str,
    level: ChunkLevel,
    chunk_index: int,
    *,
    parent_local_id: str | None = None,
    source_locators: list[dict] | tuple[dict, ...] | None = None,
    metadata: dict | None = None,
) -> NormalizedChunk:
    return NormalizedChunk(
        local_id=local_id,
        level=level,
        parent_local_id=parent_local_id,
        chunk_index=chunk_index,
        block_type=BlockType.TEXT,
        content=f"content-{local_id}",
        title_path=["Section"],
        token_count=3,
        page_start=1,
        page_end=1,
        source_locators=(
            [{"page": 1, "block": chunk_index}]
            if source_locators is None
            else source_locators
        ),
        atomic_block_indexes=[chunk_index],
        overlap_prefix_tokens=0,
        content_hash=f"hash-{local_id}",
        metadata={"origin": "test"} if metadata is None else metadata,
    )


def test_legacy_parsed_block_defaults_to_text_and_keeps_old_constructor() -> None:
    block = ParsedBlock(0, "legacy", 1, ["Section"], {"lineStart": 1})

    assert block.index == 0
    assert block.content == "legacy"
    assert block.page_no == 1
    assert block.title_path == ["Section"]
    assert block.source_locator == {"lineStart": 1}
    assert block.block_type is BlockType.TEXT
    assert block.structural_id is None
    assert block.parent_structural_id is None
    assert block.metadata == {}


def test_atomic_block_rejects_blank_content() -> None:
    with pytest.raises(ValueError, match="content"):
        AtomicBlock(
            index=0,
            content=" \n\t",
            block_type=BlockType.TEXT,
            source_locator={"lineStart": 1},
        )


def test_atomic_block_requires_source_locator_argument() -> None:
    with pytest.raises(TypeError, match="source_locator"):
        AtomicBlock(index=0, content="body", block_type=BlockType.TEXT)


def test_atomic_block_rejects_empty_source_locator() -> None:
    with pytest.raises(ValueError, match="non-empty source locator"):
        AtomicBlock(
            index=0,
            content="body",
            block_type=BlockType.TEXT,
            source_locator={},
        )


def test_json_fields_are_recursively_frozen_and_detached_from_input_aliases() -> None:
    metadata = {"labels": ["original"], "nested": {"valid": True}}
    locator = {"page": 1, "spans": [{"start": 0, "end": 4}]}
    block = AtomicBlock(
        index=0,
        content="body",
        block_type=BlockType.TEXT,
        source_locator=locator,
        metadata=metadata,
    )

    metadata["labels"].append(object())
    metadata["nested"]["invalid"] = object()
    locator["spans"][0]["invalid"] = object()

    assert block.metadata == {
        "labels": ("original",),
        "nested": {"valid": True},
    }
    assert block.source_locator == {
        "page": 1,
        "spans": ({"start": 0, "end": 4},),
    }
    with pytest.raises(TypeError):
        block.metadata["added"] = "forbidden"  # type: ignore[index]
    with pytest.raises(TypeError):
        block.source_locator["page"] = 2  # type: ignore[index]


def test_reused_frozen_json_mapping_is_not_rebuilt() -> None:
    original = AtomicBlock(
        index=0,
        content="body",
        block_type=BlockType.TEXT,
        source_locator={"page": 1, "spans": [{"start": 0, "end": 4}]},
        metadata={"nested": {"safe": True}},
    )

    reused = AtomicBlock(
        index=1,
        content="body",
        block_type=BlockType.TEXT,
        source_locator=original.source_locator,
        metadata=original.metadata,
    )

    assert reused.source_locator is original.source_locator
    assert reused.metadata is original.metadata


def test_frozen_json_fields_cannot_be_modified_to_bypass_validation() -> None:
    block = AtomicBlock(
        index=0,
        content="body",
        block_type=BlockType.TEXT,
        source_locator={"lineStart": 1},
        metadata={"nested": ["safe"]},
    )

    assert isinstance(block.metadata, Mapping)
    assert not isinstance(block.metadata, dict)
    with pytest.raises(TypeError):
        block.metadata["unsafe"] = object()  # type: ignore[index]
    with pytest.raises(AttributeError):
        block.metadata["nested"].append(object())
    with pytest.raises(TypeError):
        dict.__setitem__(block.metadata, "unsafe", object())


def test_frozen_json_mapping_copy_deepcopy_and_pickle_round_trip() -> None:
    block = AtomicBlock(
        index=0,
        content="body",
        block_type=BlockType.TEXT,
        source_locator={"lineStart": 1},
        metadata={"nested": ["safe"], "details": {"valid": True}},
    )

    assert copy.copy(block.metadata) is block.metadata
    assert copy.deepcopy(block.metadata) is block.metadata

    restored = pickle.loads(pickle.dumps(block.metadata))
    assert restored == block.metadata
    assert isinstance(restored, Mapping)
    assert not isinstance(restored, dict)
    with pytest.raises(TypeError):
        restored["unsafe"] = object()


def test_to_json_value_recursively_thaws_for_standard_json_consumers() -> None:
    block = AtomicBlock(
        index=0,
        content="body",
        block_type=BlockType.TEXT,
        source_locator={"spans": [{"start": 0, "end": 4}]},
        metadata={"labels": ["safe"], "nested": {"valid": True}},
    )

    thawed = to_json_value(block.metadata)

    assert thawed == {
        "labels": ["safe"],
        "nested": {"valid": True},
    }
    assert isinstance(thawed, dict)
    assert isinstance(thawed["labels"], list)
    json.dumps(thawed, allow_nan=False, sort_keys=True)
    thawed["labels"].append("detached")
    assert block.metadata["labels"] == ("safe",)


def test_atomic_block_normalizes_internal_sequences_and_is_frozen() -> None:
    block = AtomicBlock(
        index=0,
        content="body",
        block_type=BlockType.TEXT,
        title_path=["Chapter", "Section"],
        source_locator={"lineStart": 1, "lineEnd": 2},
        metadata={"labels": ["example"]},
    )

    assert block.title_path == ("Chapter", "Section")
    with pytest.raises(FrozenInstanceError):
        block.content = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("factory", [AtomicBlock, _chunk])
def test_contract_metadata_must_be_json_safe(factory) -> None:
    if factory is AtomicBlock:
        kwargs = {
            "index": 0,
            "content": "body",
            "block_type": BlockType.TEXT,
            "source_locator": {"lineStart": 1},
            "metadata": {"unsafe": object()},
        }
    else:
        kwargs = {
            "local_id": "child-0",
            "level": ChunkLevel.CHILD,
            "chunk_index": 0,
            "metadata": {"unsafe": object()},
        }

    with pytest.raises(ValueError, match="JSON-safe"):
        factory(**kwargs)


@pytest.mark.parametrize(
    "source_locators",
    [
        [],
        [{}],
        [{"page": 1}, {}],
    ],
)
def test_normalized_chunk_requires_non_empty_source_locator_mappings(
    source_locators,
) -> None:
    with pytest.raises(ValueError, match="non-empty source locator"):
        _chunk(
            "child-0",
            ChunkLevel.CHILD,
            0,
            source_locators=source_locators,
        )


def test_normalized_chunk_normalizes_internal_sequences() -> None:
    chunk = _chunk("child-0", ChunkLevel.CHILD, 0)

    assert chunk.title_path == ("Section",)
    assert chunk.source_locators == ({"page": 1, "block": 0},)
    assert chunk.atomic_block_indexes == (0,)


def test_chunking_result_preserves_parent_and_child_order_as_tuples() -> None:
    parent_1 = _chunk("parent-1", ChunkLevel.PARENT, 1)
    parent_0 = _chunk("parent-0", ChunkLevel.PARENT, 0)
    child_1 = _chunk(
        "child-1",
        ChunkLevel.CHILD,
        1,
        parent_local_id="parent-1",
    )
    child_0 = _chunk(
        "child-0",
        ChunkLevel.CHILD,
        0,
        parent_local_id="parent-0",
    )

    result = ChunkingResult(
        parents=[parent_1, parent_0],
        children=[child_1, child_0],
        stats=ChunkingStats(),
        warnings=[ChunkingWarning(code="TEST_WARNING", message="test")],
    )

    assert result.parents == (parent_1, parent_0)
    assert result.children == (child_1, child_0)
    assert result.warnings == (
        ChunkingWarning(code="TEST_WARNING", message="test"),
    )


def test_block_type_serialization_is_stable() -> None:
    assert json.loads(json.dumps(list(BlockType))) == [
        "TITLE",
        "HEADING",
        "TEXT",
        "LIST",
        "TABLE",
        "CODE",
        "FORMULA",
        "IMAGE",
        "QUOTE",
        "UNKNOWN",
    ]
