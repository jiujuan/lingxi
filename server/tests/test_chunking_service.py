from __future__ import annotations

import copy
import hashlib
import pickle
import re
import unicodedata
from dataclasses import FrozenInstanceError, dataclass, replace

import pytest

import server.app.services.chunking.normalization as normalization_module
import server.app.services.chunking.service as service_module

from server.app.services.chunking import (
    AtomicBlock,
    BlockType,
    ChunkLevel,
    ChunkPolicy,
    ChunkSplitNoProgressError,
    ChunkingFeatureUnsupportedError,
    ChunkingService,
    TYPE_HANDLER_VERSIONS,
)


@dataclass(frozen=True)
class WhitespaceTokenCounter:
    name: str = "service-whitespace-fixture"
    version: str = "1.0"

    def count(self, text: str) -> int:
        return len(text.split())

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        if not text:
            return []
        matches = list(re.finditer(r"\S+(?:\s+|$)", text))
        if not matches:
            return [text]
        pieces: list[str] = []
        start = 0
        for index in range(limit, len(matches), limit):
            end = matches[index - 1].end()
            pieces.append(text[start:end])
            start = end
        pieces.append(text[start:])
        return pieces


@dataclass(frozen=True)
class CharacterTokenCounter:
    name: str = "service-character-fixture"
    version: str = "1.0"

    def count(self, text: str) -> int:
        return len(text)

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        return [text[index : index + limit] for index in range(0, len(text), limit)]


def policy(
    *,
    max_tokens: int = 8,
    parent_max_tokens: int | None = None,
    allow_cross_page_merge: bool = True,
    overlap_tokens: int = 1,
    counter: WhitespaceTokenCounter | None = None,
) -> ChunkPolicy:
    tokenizer = counter or WhitespaceTokenCounter()
    return ChunkPolicy(
        tokenizer_name=tokenizer.name,
        tokenizer_version=tokenizer.version,
        min_tokens=2,
        target_tokens=max(2, max_tokens - 2),
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
        parent_max_tokens=parent_max_tokens or max_tokens * 2,
        embedding_provider_input_limit=max_tokens * 4,
        allow_cross_page_merge=allow_cross_page_merge,
        type_handler_versions={
            "table": "1.0",
            "code": "1.0",
            "image": "1.0",
            "formula": "1.0",
            "list": "1.0",
        },
    )


def atomic(
    index: int,
    content: str,
    *,
    block_type: BlockType = BlockType.TEXT,
    page_no: int | None = 1,
    title_path: tuple[str, ...] = ("Guide", "Section"),
    parent_structural_id: str | None = "section-1",
    source_identity: str | None = "document-a",
    metadata: dict[str, object] | None = None,
) -> AtomicBlock:
    locator: dict[str, object] = {
        "block": index,
        "page": page_no,
        "selfRef": f"#/blocks/{index}",
    }
    if source_identity is not None:
        locator["sourceIdentity"] = source_identity
    return AtomicBlock(
        index=index,
        content=content,
        block_type=block_type,
        source_locator=locator,
        page_no=page_no,
        title_path=title_path,
        structural_id=f"block-{index}",
        parent_structural_id=parent_structural_id,
        metadata=metadata or {},
    )


def test_empty_input_returns_an_immutable_zero_result() -> None:
    counter = WhitespaceTokenCounter()
    result = ChunkingService(counter).chunk(
        [], policy(counter=counter), document_title="Empty"
    )

    assert result.parents == ()
    assert result.children == ()
    assert result.warnings == ()
    assert result.stats.input_block_count == 0
    assert result.stats.parent_count == 0
    assert result.stats.child_count == 0
    assert result.stats.skipped_block_count == 0
    assert result.stats.total_token_count == 0
    assert copy.deepcopy(result) == result
    assert pickle.loads(pickle.dumps(result)) == result


def test_service_sorts_normalizes_merges_and_assigns_stable_hierarchy() -> None:
    counter = WhitespaceTokenCounter()
    blocks = [
        atomic(30, "  second\r\npart  "),
        atomic(10, "first"),
    ]

    result = ChunkingService(counter).chunk(
        blocks, policy(max_tokens=8, counter=counter), document_title="Guide"
    )

    assert [child.chunk_index for child in result.children] == [0]
    assert [child.local_id for child in result.children] == ["child-000000"]
    assert result.children[0].content == "first\n\nsecond\npart"
    assert result.children[0].atomic_block_indexes == (10, 30)
    assert result.children[0].level is ChunkLevel.CHILD
    assert result.children[0].parent_local_id == "parent-000000"
    assert [parent.local_id for parent in result.parents] == ["parent-000000"]
    assert result.parents[0].chunk_index == 0
    assert result.parents[0].metadata["childLocalIds"] == ("child-000000",)
    assert result.parents[0].content == result.children[0].content
    assert result.stats.child_count == len(result.children)
    assert result.stats.parent_count == len(result.parents)
    assert result.stats.total_token_count == sum(
        child.token_count for child in result.children
    )


def test_oversized_prose_applies_overlap_but_parent_uses_unique_content() -> None:
    counter = WhitespaceTokenCounter()
    source = "one two three four five six seven eight nine ten eleven twelve thirteen"

    result = ChunkingService(counter).chunk(
        [atomic(4, source)],
        policy(max_tokens=7, parent_max_tokens=14, counter=counter),
        document_title="Guide",
    )

    assert len(result.children) >= 2
    assert all(child.overlap_prefix_tokens == 1 for child in result.children[1:])
    for previous, current in zip(result.children, result.children[1:]):
        repeated_word = current.content.split()[0]
        assert repeated_word in previous.content.split()
        assert result.parents[0].content.split().count(repeated_word) == 1
    assert result.parents[0].content.split() == source.split()
    assert result.parents[0].token_count == counter.count(source)
    assert result.children[1].metadata["overlap"]["prefix_token_count"] == 1


def test_parent_overflow_segments_only_at_child_boundaries() -> None:
    counter = WhitespaceTokenCounter()
    blocks = [
        atomic(0, "alpha beta gamma delta", metadata={"hard_boundary": True}),
        atomic(1, "echo foxtrot golf hotel", metadata={"hard_boundary": True}),
        atomic(2, "india juliet", metadata={"hard_boundary": True}),
    ]

    result = ChunkingService(counter).chunk(
        blocks,
        policy(max_tokens=4, parent_max_tokens=6, counter=counter),
        document_title="Guide",
    )

    assert [parent.content for parent in result.parents] == [
        "alpha beta gamma delta",
        "echo foxtrot golf hotel\n\nindia juliet",
    ]
    assert all(parent.token_count <= 6 for parent in result.parents)
    assert [parent.metadata["childIndexes"] for parent in result.parents] == [
        (0,),
        (1, 2),
    ]
    assert [child.parent_local_id for child in result.children] == [
        "parent-000000",
        "parent-000001",
        "parent-000001",
    ]
    assert all("parentContent" not in child.metadata for child in result.children)


def test_parent_groups_by_section_not_page_and_never_crosses_section() -> None:
    counter = WhitespaceTokenCounter()
    blocks = [
        atomic(0, "page one", page_no=1),
        atomic(1, "page two", page_no=2),
        atomic(
            2,
            "other section",
            page_no=2,
            title_path=("Guide", "Other"),
            parent_structural_id="section-2",
        ),
    ]

    result = ChunkingService(counter).chunk(
        blocks,
        policy(max_tokens=6, parent_max_tokens=12, counter=counter),
        document_title="Guide",
    )

    assert len(result.parents) == 2
    assert result.parents[0].page_start == 1
    assert result.parents[0].page_end == 2
    assert result.parents[0].title_path == ("Guide", "Section")
    assert result.parents[1].title_path == ("Guide", "Other")

    no_cross_page_merge = ChunkingService(counter).chunk(
        blocks[:2],
        policy(
            max_tokens=6,
            parent_max_tokens=12,
            allow_cross_page_merge=False,
            counter=counter,
        ),
        document_title="Guide",
    )
    assert len(no_cross_page_merge.children) == 2
    assert len(no_cross_page_merge.parents) == 1


def test_typed_handler_context_uses_source_identity_and_dense_position() -> None:
    counter = WhitespaceTokenCounter()
    blocks = [
        atomic(10, "nearby explanation", page_no=3),
        atomic(
            90,
            "diagram payload",
            block_type=BlockType.IMAGE,
            page_no=3,
            metadata={"caption": "Architecture"},
        ),
    ]

    result = ChunkingService(counter).chunk(
        blocks,
        policy(max_tokens=16, parent_max_tokens=32, counter=counter),
        document_title="Guide",
    )

    image_child = next(
        child for child in result.children if child.block_type is BlockType.IMAGE
    )
    assert "Context: nearby explanation" in image_child.content
    assert image_child.atomic_block_indexes == (10, 90)


def test_typed_handler_does_not_absorb_neighbor_from_another_source() -> None:
    counter = WhitespaceTokenCounter()
    blocks = [
        atomic(10, "secret other document", page_no=3, source_identity="document-b"),
        atomic(
            90,
            "diagram payload",
            block_type=BlockType.IMAGE,
            page_no=3,
            source_identity="document-a",
            metadata={"caption": "Architecture"},
        ),
    ]

    result = ChunkingService(counter).chunk(
        blocks,
        policy(max_tokens=16, parent_max_tokens=32, counter=counter),
        document_title="Guide",
    )

    image_child = next(
        child for child in result.children if child.block_type is BlockType.IMAGE
    )
    assert "secret other document" not in image_child.content
    assert image_child.atomic_block_indexes == (90,)


def test_unknown_is_conservatively_treated_as_text_and_warning_is_auditable() -> None:
    counter = WhitespaceTokenCounter()
    result = ChunkingService(counter).chunk(
        [atomic(7, "unknown body", block_type=BlockType.UNKNOWN)],
        policy(counter=counter),
        document_title="Guide",
    )

    assert result.children[0].block_type is BlockType.TEXT
    assert result.children[0].metadata["originalBlockType"] == "UNKNOWN"
    warning = next(
        warning
        for warning in result.warnings
        if warning.code == "UNKNOWN_BLOCK_TYPE_NORMALIZED"
    )
    assert warning.metadata["atomicBlockIndex"] == 7


def test_handler_warnings_and_skips_are_aggregated_into_stats() -> None:
    counter = WhitespaceTokenCounter()
    result = ChunkingService(counter).chunk(
        [
            atomic(
                2,
                "image binary placeholder",
                block_type=BlockType.IMAGE,
                metadata={},
            )
        ],
        policy(counter=counter),
        document_title="Guide",
    )

    assert result.children == ()
    assert result.parents == ()
    assert result.stats.input_block_count == 1
    assert result.stats.skipped_block_count == 1
    assert [warning.code for warning in result.warnings] == [
        "IMAGE_WITHOUT_TEXT_SKIPPED"
    ]


def test_hashes_metadata_and_full_result_are_deterministic_and_normalized() -> None:
    counter = WhitespaceTokenCounter()
    service = ChunkingService(counter)
    first_block = atomic(0, "  Cafe\u0301\r\nbody  ")
    second_block = atomic(0, "Caf\u00e9\nbody")
    chunk_policy = policy(counter=counter)

    first = service.chunk(
        [first_block], chunk_policy, document_title="Cafe\u0301 Guide"
    )
    repeated = service.chunk(
        [first_block], chunk_policy, document_title="Cafe\u0301 Guide"
    )
    normalized = service.chunk(
        [second_block], chunk_policy, document_title="Caf\u00e9 Guide"
    )

    assert first == repeated
    assert [child.content for child in first.children] == [
        child.content for child in normalized.children
    ]
    assert [child.content_hash for child in first.children] == [
        child.content_hash for child in normalized.children
    ]
    assert first.children[0].source_locators != normalized.children[0].source_locators
    child = first.children[0]
    expected_content = unicodedata.normalize("NFC", "Caf\u00e9\nbody")
    assert child.content == expected_content
    assert child.content_hash == hashlib.sha256(expected_content.encode()).hexdigest()
    assert child.metadata["chunker"]["configHash"] == chunk_policy.config_hash
    assert child.metadata["chunker"]["tokenizerName"] == counter.name
    assert (
        first.parents[0].metadata["chunker"]["configHash"]
        == chunk_policy.config_hash
    )
    assert pickle.loads(pickle.dumps(first)) == first
    with pytest.raises(FrozenInstanceError):
        child.chunk_index = 99  # type: ignore[misc]
    with pytest.raises(TypeError):
        child.metadata["new"] = True  # type: ignore[index]


def test_service_rejects_duplicate_indexes_and_tokenizer_policy_mismatch() -> None:
    counter = WhitespaceTokenCounter()
    service = ChunkingService(counter)

    with pytest.raises(ValueError, match="duplicate AtomicBlock.index"):
        service.chunk(
            [atomic(1, "one"), atomic(1, "two")],
            policy(counter=counter),
            document_title="Guide",
        )

    mismatched = ChunkPolicy(
        tokenizer_name="other",
        tokenizer_version="9",
        min_tokens=2,
        target_tokens=4,
        max_tokens=6,
        overlap_tokens=1,
        parent_max_tokens=12,
        embedding_provider_input_limit=24,
    )
    with pytest.raises(ValueError, match="tokenizer"):
        service.chunk([atomic(1, "one")], mismatched, document_title="Guide")


def test_service_rejects_invalid_inputs_without_external_side_effects() -> None:
    counter = WhitespaceTokenCounter()
    service = ChunkingService(counter)

    with pytest.raises(ValueError, match="document_title"):
        service.chunk([atomic(1, "one")], policy(counter=counter), document_title=" ")
    with pytest.raises(ValueError, match="AtomicBlock"):
        service.chunk(
            ["not-a-block"],  # type: ignore[list-item]
            policy(counter=counter),
            document_title="Guide",
        )


class CountingWhitespaceTokenCounter:
    name = "service-counting-whitespace-fixture"
    version = "1.0"

    def __init__(self) -> None:
        self.count_calls = 0
        self.counted_characters = 0

    def count(self, text: str) -> int:
        self.count_calls += 1
        self.counted_characters += len(text)
        return len(text.split())

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        return WhitespaceTokenCounter().split_by_token_limit(text, limit)


def test_registered_typed_blocks_are_strong_boundaries_before_generic_merge() -> None:
    counter = WhitespaceTokenCounter()
    blocks = [
        atomic(0, "overview"),
        atomic(
            1,
            "- alpha",
            block_type=BlockType.LIST,
            metadata={"intro": "First list", "items": ["alpha"]},
        ),
        atomic(
            2,
            "- beta",
            block_type=BlockType.LIST,
            metadata={
                "intro": " ".join(f"intro{index}" for index in range(12)),
                "items": ["beta"],
            },
        ),
        atomic(3, "closing"),
    ]

    result = ChunkingService(counter).chunk(
        blocks,
        policy(max_tokens=5, parent_max_tokens=80, counter=counter),
        document_title="Guide",
    )

    assert [child.block_type for child in result.children].count(BlockType.LIST) >= 2
    assert all(
        "list" in child.metadata
        for child in result.children
        if child.block_type is BlockType.LIST
    )
    assert any(warning.code == "LIST_PREFIX_DEGRADED" for warning in result.warnings)
    assert "overview" in result.parents[0].content
    assert "closing" in result.parents[0].content


def test_source_identity_is_a_merge_and_parent_security_boundary() -> None:
    counter = WhitespaceTokenCounter()
    result = ChunkingService(counter).chunk(
        [
            atomic(0, "source alpha", source_identity="document-a"),
            atomic(1, "source beta", source_identity="document-b"),
        ],
        policy(max_tokens=8, parent_max_tokens=16, counter=counter),
        document_title="Guide",
    )

    assert [child.atomic_block_indexes for child in result.children] == [(0,), (1,)]
    assert len(result.parents) == 2
    assert all(len(child.source_locators) == 1 for child in result.children)


def test_all_missing_source_identity_gets_stable_call_identity_and_neighbor_context() -> None:
    counter = WhitespaceTokenCounter()
    blocks = [
        atomic(10, "List introduction", source_identity=None),
        atomic(
            90,
            "- alpha\n- beta",
            block_type=BlockType.LIST,
            source_identity=None,
            metadata={"items": ["alpha", "beta"]},
        ),
    ]
    service = ChunkingService(counter)
    first = service.chunk(
        blocks,
        policy(max_tokens=8, parent_max_tokens=20, counter=counter),
        document_title="Guide",
    )
    second = service.chunk(
        blocks,
        policy(max_tokens=8, parent_max_tokens=20, counter=counter),
        document_title="Guide",
    )

    list_child = next(child for child in first.children if child.block_type is BlockType.LIST)
    assert "List introduction" in list_child.content
    assert first == second
    assert len(first.parents) == 1


@pytest.mark.parametrize(
    "blocks,match",
    [
        (
            [atomic(0, "explicit"), atomic(1, "missing", source_identity=None)],
            "source identity",
        ),
        (
            [
                AtomicBlock(
                    index=0,
                    content="bad",
                    block_type=BlockType.TEXT,
                    source_locator={"block": 0, "sourceIdentity": 123},
                )
            ],
            "source identity",
        ),
        (
            [
                AtomicBlock(
                    index=0,
                    content="conflict",
                    block_type=BlockType.TEXT,
                    source_locator={
                        "block": 0,
                        "sourceIdentity": "a",
                        "documentId": "b",
                    },
                )
            ],
            "source identity",
        ),
    ],
)
def test_partial_invalid_or_conflicting_source_identity_is_rejected(
    blocks: list[AtomicBlock], match: str
) -> None:
    counter = WhitespaceTokenCounter()
    with pytest.raises(ValueError, match=match):
        ChunkingService(counter).chunk(
            blocks,
            policy(counter=counter),
            document_title="Guide",
        )


def test_normalized_split_spans_map_back_to_original_atomic_coordinates() -> None:
    counter = WhitespaceTokenCounter()
    original = "  Cafe\u0301 one\r\ntwo three four five  "
    result = ChunkingService(counter).chunk(
        [atomic(7, original)],
        policy(
            max_tokens=3,
            parent_max_tokens=30,
            overlap_tokens=0,
            counter=counter,
        ),
        document_title="Guide",
    )

    assert len(result.children) >= 2
    reconstructed: list[str] = []
    for child in result.children:
        span = child.source_locators[0]["_lingxi_chunk_span"]
        assert span["coordinate_space"] == "original_atomic"
        assert span["normalization_version"] == "nfc-lf-strip-v2"
        assert span["merged_coordinate_space"] == "normalized_merged"
        source_slice = original[
            span["atomic_char_start"] : span["atomic_char_end"]
        ]
        normalized_slice = unicodedata.normalize("NFC", source_slice).replace(
            "\r\n", "\n"
        ).replace("\r", "\n").strip()
        assert normalized_slice == child.content
        reconstructed.append(normalized_slice)
        assert (
            span["normalized_atomic_char_start"]
            < span["normalized_atomic_char_end"]
        )
    assert "\n".join(reconstructed).split() == "Café one two three four five".split()


def test_parent_uses_typed_unique_content_for_table_and_list() -> None:
    counter = WhitespaceTokenCounter()
    table = atomic(
        0,
        "table",
        block_type=BlockType.TABLE,
        metadata={
            "caption": "Quarterly",
            "header": "Name Value",
            "rows": [f"row{index} value{index} extra" for index in range(10)],
        },
    )
    list_block = atomic(
        1,
        "- a",
        block_type=BlockType.LIST,
        metadata={"intro": "Steps now", "items": ["a", "b", "c", "d", "e", "f"]},
    )

    result = ChunkingService(counter).chunk(
        [table, list_block],
        policy(max_tokens=12, parent_max_tokens=200, counter=counter),
        document_title="Guide",
    )
    parent_content = result.parents[0].content

    table_children = [
        child for child in result.children if child.block_type is BlockType.TABLE
    ]
    list_children = [
        child for child in result.children if child.block_type is BlockType.LIST
    ]
    assert len(table_children) > 1
    assert len(list_children) > 1
    assert parent_content.count("Quarterly") == 1
    assert parent_content.count("Name Value") == 1
    assert parent_content.count("Steps now") == 1
    for index in range(10):
        assert parent_content.count(f"row{index} value{index} extra") == 1


def test_parent_excludes_image_and_formula_external_neighbor_context() -> None:
    counter = WhitespaceTokenCounter()
    blocks = [
        atomic(0, "before image"),
        atomic(
            1,
            "image payload",
            block_type=BlockType.IMAGE,
            metadata={"caption": "Architecture", "ocr": "Node A"},
        ),
        atomic(2, "formula explanation"),
        atomic(
            3,
            "x+y",
            block_type=BlockType.FORMULA,
            metadata={"latex": "x+y"},
        ),
        atomic(4, "after formula"),
    ]

    result = ChunkingService(counter).chunk(
        blocks,
        policy(max_tokens=8, parent_max_tokens=100, counter=counter),
        document_title="Guide",
    )
    parent_content = result.parents[0].content

    assert parent_content.count("before image") == 1
    assert parent_content.count("formula explanation") == 1
    assert parent_content.count("after formula") == 1
    assert parent_content.count("Architecture") == 1
    assert parent_content.count("Node A") == 1
    assert parent_content.count("x+y") == 1


def test_service_validates_exact_actual_handler_versions_before_hashing() -> None:
    counter = WhitespaceTokenCounter()
    service = ChunkingService(counter)
    valid = policy(counter=counter)
    result = service.chunk([atomic(0, "content")], valid, document_title="Guide")

    assert dict(valid.type_handler_versions) == dict(TYPE_HANDLER_VERSIONS)
    assert result.children[0].metadata["chunker"]["configHash"] == valid.config_hash
    with pytest.raises(TypeError):
        TYPE_HANDLER_VERSIONS["list"] = "9.9"  # type: ignore[index]

    invalid_versions = [
        {"table": "1.0"},
        {**dict(TYPE_HANDLER_VERSIONS), "unknown": "1.0"},
        {**dict(TYPE_HANDLER_VERSIONS), "list": "9.9"},
    ]
    for versions in invalid_versions:
        with pytest.raises(ValueError, match="type handler versions"):
            service.chunk(
                [atomic(0, "content")],
                replace(valid, type_handler_versions=versions),
                document_title="Guide",
            )

    changed_actual = replace(
        valid,
        type_handler_versions={**dict(TYPE_HANDLER_VERSIONS), "list": "9.9"},
    )
    assert changed_actual.config_hash != valid.config_hash


def test_parent_segmentation_has_bounded_tokenizer_work_for_many_children() -> None:
    counter = CountingWhitespaceTokenCounter()
    blocks = [
        atomic(
            index,
            f"item{index}",
            metadata={"hard_boundary": True},
        )
        for index in range(400)
    ]
    chunk_policy = ChunkPolicy(
        tokenizer_name=counter.name,
        tokenizer_version=counter.version,
        min_tokens=2,
        target_tokens=6,
        max_tokens=8,
        overlap_tokens=0,
        parent_max_tokens=1800,
        embedding_provider_input_limit=4096,
        type_handler_versions=TYPE_HANDLER_VERSIONS,
    )

    result = ChunkingService(counter).chunk(
        blocks, chunk_policy, document_title="Guide"
    )

    assert len(result.children) == 400
    assert len(result.parents) == 1
    assert result.parents[0].token_count == 400
    assert counter.counted_characters < 100_000


@pytest.mark.parametrize(
    ("intro", "items", "max_tokens"),
    [
        (None, ["only-item"], 8),
        ("List intro", ["only-item"], 8),
        ("List intro", ["item-one", "item-two", "item-three"], 3),
    ],
)
def test_list_parent_contains_every_item_once_and_is_never_empty(
    intro: str | None,
    items: list[str],
    max_tokens: int,
) -> None:
    counter = WhitespaceTokenCounter()
    metadata: dict[str, object] = {"items": items}
    if intro is not None:
        metadata["intro"] = intro
    result = ChunkingService(counter).chunk(
        [
            atomic(
                0,
                "\n".join(f"- {item}" for item in items),
                block_type=BlockType.LIST,
                metadata=metadata,
            )
        ],
        policy(
            max_tokens=max_tokens,
            parent_max_tokens=64,
            overlap_tokens=0,
            counter=counter,
        ),
        document_title="List Guide",
    )

    assert result.parents
    parent_content = "\n\n".join(parent.content for parent in result.parents)
    assert parent_content.strip()
    if intro is not None:
        assert parent_content.count(intro) == 1
    for item in items:
        assert parent_content.count(f"- {item}") == 1


def test_normalization_spans_handle_repeated_composed_and_decomposed_clusters() -> None:
    counter = CharacterTokenCounter()
    raw = "aaaae\u0301aaaaéaaaa"
    chunk_policy = ChunkPolicy(
        tokenizer_name=counter.name,
        tokenizer_version=counter.version,
        min_tokens=2,
        target_tokens=3,
        max_tokens=4,
        overlap_tokens=0,
        parent_max_tokens=32,
        embedding_provider_input_limit=64,
        type_handler_versions=TYPE_HANDLER_VERSIONS,
    )

    result = ChunkingService(counter).chunk(
        [atomic(0, raw)], chunk_policy, document_title="Unicode"
    )

    assert len(result.children) > 1
    reconstructed: list[str] = []
    for child in result.children:
        assert len(child.source_locators) == 1
        span = child.source_locators[0]["_lingxi_chunk_span"]
        start = span["atomic_char_start"]
        end = span["atomic_char_end"]
        assert 0 <= start < end <= len(raw)
        source_fragment = unicodedata.normalize("NFC", raw[start:end]).strip()
        assert source_fragment == child.content
        reconstructed.append(source_fragment)
    assert "".join(reconstructed) == unicodedata.normalize("NFC", raw)


def test_normalization_mapping_reports_linear_work_for_large_repeated_input() -> None:
    counter = CharacterTokenCounter()
    raw = "a" * 1024 + "e\u0301" * 128 + "é" * 128
    chunk_policy = ChunkPolicy(
        tokenizer_name=counter.name,
        tokenizer_version=counter.version,
        min_tokens=512,
        target_tokens=1400,
        max_tokens=1600,
        overlap_tokens=0,
        parent_max_tokens=2000,
        embedding_provider_input_limit=4096,
        type_handler_versions=TYPE_HANDLER_VERSIONS,
    )

    result = ChunkingService(counter).chunk(
        [atomic(0, raw)], chunk_policy, document_title="Scale"
    )

    span = result.children[0].source_locators[0]["_lingxi_chunk_span"]
    assert span["normalization_work_units"] <= len(raw) * 8
    assert result.children[0].content == unicodedata.normalize("NFC", raw)


def test_normalization_cluster_detection_is_linear_for_long_combining_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = "a" + "\u0315\u0300" * 512 + "z"
    calls = 0
    original = normalization_module._starts_with_nonstarter

    def counted(value: str) -> bool:
        nonlocal calls
        calls += 1
        return original(value)

    monkeypatch.setattr(normalization_module, "_starts_with_nonstarter", counted)
    normalized, metadata = normalization_module.normalize_text_with_map(raw)

    assert normalized == unicodedata.normalize("NFC", raw)
    assert calls <= len(raw) * 4
    assert metadata["normalizationWorkUnits"] <= len(raw) * 8


def test_normalization_spans_preserve_canonical_combining_mark_reordering() -> None:
    counter = CharacterTokenCounter()
    raw = "  a\u0315\u0300\r\nb\u0301  "
    chunk_policy = ChunkPolicy(
        tokenizer_name=counter.name,
        tokenizer_version=counter.version,
        min_tokens=1,
        target_tokens=2,
        max_tokens=2,
        overlap_tokens=0,
        parent_max_tokens=16,
        embedding_provider_input_limit=32,
        type_handler_versions=TYPE_HANDLER_VERSIONS,
    )

    result = ChunkingService(counter).chunk(
        [atomic(0, raw)], chunk_policy, document_title="Canonical order"
    )

    assert result.children
    for child in result.children:
        span = child.source_locators[0]["_lingxi_chunk_span"]
        start = span["atomic_char_start"]
        end = span["atomic_char_end"]
        assert start < end
        assert normalization_module.normalize_text(raw[start:end]) == child.content


def test_code_offsets_use_original_atomic_coordinates_after_normalization() -> None:
    counter = WhitespaceTokenCounter()
    raw = "  def café():\r\n    value = 'e\u0301'\r\n    return value\r\n  "
    result = ChunkingService(counter).chunk(
        [atomic(0, raw, block_type=BlockType.CODE, metadata={"language": "python"})],
        policy(
            max_tokens=4,
            parent_max_tokens=64,
            overlap_tokens=0,
            counter=counter,
        ),
        document_title="Code",
    )

    assert len(result.children) > 1
    for child in result.children:
        code = child.metadata["code"]
        start = code["sourceCharStart"]
        end = code["sourceCharEnd"]
        assert code["sourceCoordinateSpace"] == "original_atomic"
        assert code["normalizedCoordinateSpace"] == "normalized_atomic"
        assert code["normalizationVersion"] == "nfc-lf-strip-v2"
        assert 0 <= start < end <= len(raw)
        assert unicodedata.normalize("NFC", raw[start:end].replace("\r\n", "\n").replace("\r", "\n")).strip() == code["sourceText"]
        normalized_start = code["normalizedSourceCharStart"]
        normalized_end = code["normalizedSourceCharEnd"]
        assert normalized_start < normalized_end
        assert code["sourceText"] in child.content


def test_semantic_split_true_is_rejected_until_supported() -> None:
    counter = WhitespaceTokenCounter()
    service = ChunkingService(counter)
    default_policy = policy(counter=counter)

    supported = service.chunk(
        [atomic(0, "ordinary text")],
        default_policy,
        document_title="Guide",
    )
    assert supported.children

    with pytest.raises(ChunkingFeatureUnsupportedError) as exc_info:
        service.chunk(
            [atomic(0, "ordinary text")],
            replace(default_policy, semantic_split_enabled=True),
            document_title="Guide",
        )
    assert exc_info.value.code == "CHUNK_FEATURE_UNSUPPORTED"
    assert exc_info.value.feature == "semantic_split_enabled"
    assert exc_info.value.retryable is False


def test_normalization_uses_only_bounded_unicode_normalize_inputs_for_long_cluster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_normalize = normalization_module.unicodedata.normalize

    def measured(run_length: int) -> tuple[str, int, int]:
        input_lengths: list[int] = []

        def counted(form: str, value: str) -> str:
            input_lengths.append(len(value))
            return original_normalize(form, value)

        monkeypatch.setattr(normalization_module.unicodedata, "normalize", counted)
        raw = "a" + "\u0315\u0300" * run_length + "z"
        normalized, _ = normalization_module.normalize_text_with_map(raw)
        monkeypatch.setattr(
            normalization_module.unicodedata, "normalize", original_normalize
        )
        return normalized, max(input_lengths, default=0), sum(input_lengths)

    small_raw = "a" + "\u0315\u0300" * 128 + "z"
    large_raw = "a" + "\u0315\u0300" * 256 + "z"
    small, small_max, small_total = measured(128)
    large, large_max, large_total = measured(256)

    assert small == original_normalize("NFC", small_raw)
    assert large == original_normalize("NFC", large_raw)
    assert small_max <= 2
    assert large_max <= 2
    assert large_total <= small_total * 3


@pytest.mark.parametrize("block_type", [BlockType.TEXT, BlockType.CODE])
def test_service_splits_only_at_canonical_normalization_segment_boundaries(
    block_type: BlockType,
) -> None:
    counter = CharacterTokenCounter()
    raw = "xa\u0315\u0300"
    chunk_policy = ChunkPolicy(
        tokenizer_name=counter.name,
        tokenizer_version=counter.version,
        min_tokens=1,
        target_tokens=2,
        max_tokens=2,
        overlap_tokens=0,
        parent_max_tokens=8,
        embedding_provider_input_limit=16,
        type_handler_versions=TYPE_HANDLER_VERSIONS,
    )
    metadata = {"language": "text"} if block_type is BlockType.CODE else {}

    result = ChunkingService(counter).chunk(
        [atomic(0, raw, block_type=block_type, metadata=metadata)],
        chunk_policy,
        document_title="Canonical boundary",
    )

    assert [child.content for child in result.children] == ["x", "à\u0315"]
    assert all(child.token_count <= chunk_policy.max_tokens for child in result.children)
    for child in result.children:
        if block_type is BlockType.TEXT:
            span = child.source_locators[0]["_lingxi_chunk_span"]
            start = span["atomic_char_start"]
            end = span["atomic_char_end"]
            assert 0 <= start < end <= len(raw)
            assert normalization_module.normalize_text(raw[start:end]) == child.content
        else:
            code = child.metadata["code"]
            start = code["sourceCharStart"]
            end = code["sourceCharEnd"]
            assert 0 <= start < end <= len(raw)
            assert normalization_module.normalize_text(raw[start:end]) == child.content
            assert code["sourceText"] == child.content
            assert code["normalizedSourceCharStart"] in {0, 1}
            assert code["normalizedSourceCharEnd"] in {1, 3}


def test_long_single_list_item_uses_fragment_unique_content_for_parent_budget() -> None:
    counter = WhitespaceTokenCounter()
    item_tokens = [f"step{index}" for index in range(20)]
    result = ChunkingService(counter).chunk(
        [
            atomic(
                0,
                "- " + " ".join(item_tokens),
                block_type=BlockType.LIST,
                metadata={"intro": "Steps", "items": [" ".join(item_tokens)]},
            )
        ],
        policy(
            max_tokens=4,
            parent_max_tokens=8,
            overlap_tokens=0,
            counter=counter,
        ),
        document_title="Long list",
    )

    assert result.children
    assert result.parents
    assert all(child.token_count <= 4 for child in result.children)
    assert all(parent.token_count <= 8 for parent in result.parents)
    parent_content = "\n\n".join(parent.content for parent in result.parents)
    assert parent_content.count("Steps") == 1
    for token in item_tokens:
        assert parent_content.split().count(token) == 1


@pytest.mark.parametrize("block_type", [BlockType.TEXT, BlockType.CODE])
def test_oversized_single_normalization_segment_uses_explicit_fragment_provenance(
    block_type: BlockType,
) -> None:
    counter = CharacterTokenCounter()
    raw = "a\u0315\u0300\u0315\u0300"
    chunk_policy = ChunkPolicy(
        tokenizer_name=counter.name,
        tokenizer_version=counter.version,
        min_tokens=1,
        target_tokens=2,
        max_tokens=2,
        overlap_tokens=0,
        parent_max_tokens=8,
        embedding_provider_input_limit=16,
        type_handler_versions=TYPE_HANDLER_VERSIONS,
    )
    metadata = {"language": "text"} if block_type is BlockType.CODE else {}

    result = ChunkingService(counter).chunk(
        [atomic(0, raw, block_type=block_type, metadata=metadata)],
        chunk_policy,
        document_title="Oversized canonical segment",
    )

    assert len(result.children) > 1
    assert all(child.token_count <= 2 for child in result.children)
    assert "".join(
        child.content for child in result.children
    ) == normalization_module.normalize_text(raw)
    for child in result.children:
        if block_type is BlockType.TEXT:
            span = child.source_locators[0]["_lingxi_chunk_span"]
            assert span["coordinate_space"] == "normalized_atomic_segment_fragment"
            assert span["provenance_mode"] == "normalization_segment_fragment"
            assert "atomic_char_start" not in span
            assert span["original_segment_char_start"] < span["original_segment_char_end"]
        else:
            code = child.metadata["code"]
            assert code["sourceCoordinateSpace"] == "normalized_atomic_segment_fragment"
            assert code["sourceProvenanceMode"] == "normalization_segment_fragment"
            assert code["sourceSpanSemantics"] == "containing_normalization_segment"


@pytest.mark.parametrize("block_type", [BlockType.TEXT, BlockType.CODE])
def test_single_source_code_point_decomposition_is_one_reversible_segment(
    block_type: BlockType,
) -> None:
    counter = CharacterTokenCounter()
    raw = "x\u0FA7"
    normalized, normalization = normalization_module.normalize_text_with_map(raw)

    assert normalized == "x\u0FA6\u0FB7"
    assert normalization_module.normalized_segment_boundaries(normalization) == (0, 1, 3)

    chunk_policy = ChunkPolicy(
        tokenizer_name=counter.name,
        tokenizer_version=counter.version,
        min_tokens=1,
        target_tokens=2,
        max_tokens=2,
        overlap_tokens=0,
        parent_max_tokens=8,
        embedding_provider_input_limit=16,
        type_handler_versions=TYPE_HANDLER_VERSIONS,
    )
    metadata = {"language": "text"} if block_type is BlockType.CODE else {}

    result = ChunkingService(counter).chunk(
        [atomic(0, raw, block_type=block_type, metadata=metadata)],
        chunk_policy,
        document_title="Single source unit decomposition",
    )

    assert [child.content for child in result.children] == ["x", "\u0FA6\u0FB7"]
    assert all(child.token_count <= chunk_policy.max_tokens for child in result.children)
    for child in result.children:
        if block_type is BlockType.TEXT:
            span = child.source_locators[0]["_lingxi_chunk_span"]
            start = span["atomic_char_start"]
            end = span["atomic_char_end"]
        else:
            code = child.metadata["code"]
            assert code["sourceCoordinateSpace"] == "original_atomic"
            start = code["sourceCharStart"]
            end = code["sourceCharEnd"]
        assert 0 <= start < end <= len(raw)
        assert normalization_module.normalize_text(raw[start:end]) == child.content


@pytest.mark.parametrize("block_type", [BlockType.TEXT, BlockType.CODE])
def test_oversized_single_source_unit_decomposition_uses_fragment_provenance(
    block_type: BlockType,
) -> None:
    counter = CharacterTokenCounter()
    raw = "x\u0FA7"
    chunk_policy = ChunkPolicy(
        tokenizer_name=counter.name,
        tokenizer_version=counter.version,
        min_tokens=1,
        target_tokens=1,
        max_tokens=1,
        overlap_tokens=0,
        parent_max_tokens=8,
        embedding_provider_input_limit=16,
        type_handler_versions=TYPE_HANDLER_VERSIONS,
    )
    metadata = {"language": "text"} if block_type is BlockType.CODE else {}

    result = ChunkingService(counter).chunk(
        [atomic(0, raw, block_type=block_type, metadata=metadata)],
        chunk_policy,
        document_title="Oversized source unit decomposition",
    )

    assert "".join(
        child.content for child in result.children
    ) == normalization_module.normalize_text(raw)
    assert all(child.token_count <= chunk_policy.max_tokens for child in result.children)
    fragments = []
    for child in result.children:
        if block_type is BlockType.TEXT:
            span = child.source_locators[0]["_lingxi_chunk_span"]
            if span["coordinate_space"] == "original_atomic":
                start = span["atomic_char_start"]
                end = span["atomic_char_end"]
                assert normalization_module.normalize_text(raw[start:end]) == child.content
            else:
                fragments.append(span)
                assert span["coordinate_space"] == "normalized_atomic_segment_fragment"
                assert span["provenance_mode"] == "normalization_segment_fragment"
                assert "atomic_char_start" not in span
                assert "atomic_char_end" not in span
                assert span["original_segment_char_start"] == 1
                assert span["original_segment_char_end"] == 2
        else:
            code = child.metadata["code"]
            if code["sourceCoordinateSpace"] == "original_atomic":
                assert normalization_module.normalize_text(
                    raw[code["sourceCharStart"] : code["sourceCharEnd"]]
                ) == child.content
            else:
                fragments.append(code)
                assert (
                    code["sourceCoordinateSpace"]
                    == "normalized_atomic_segment_fragment"
                )
                assert code["sourceProvenanceMode"] == "normalization_segment_fragment"
                assert code["sourceSpanSemantics"] == "containing_normalization_segment"
                assert code["originalSegmentCharStart"] == 1
                assert code["originalSegmentCharEnd"] == 2
    assert len(fragments) == 2


def test_code_normalization_mapping_failure_uses_structured_split_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter = CharacterTokenCounter()
    raw = "abc"

    def malformed_map(text: str) -> tuple[str, dict[str, object]]:
        assert text == raw
        return text, {
            "version": normalization_module.NORMALIZATION_VERSION,
            "coordinateSpace": "normalized_atomic",
            "originalCoordinateSpace": "original_atomic",
            "originalLength": len(text),
            "normalizedLength": len(text),
            "charMap": [[index, index + 1] for index in range(len(text))],
            "segments": [
                {
                    "normalizedStart": 0,
                    "normalizedEnd": 1,
                    "originalStart": 0,
                    "originalEnd": 1,
                }
            ],
            "normalizationWorkUnits": len(text),
            "originalText": text,
        }

    monkeypatch.setattr(service_module, "normalize_text_with_map", malformed_map)

    with pytest.raises(ChunkSplitNoProgressError) as exc_info:
        ChunkingService(counter).chunk(
            [atomic(0, raw, block_type=BlockType.CODE, metadata={"language": "text"})],
            ChunkPolicy(
                tokenizer_name=counter.name,
                tokenizer_version=counter.version,
                min_tokens=1,
                target_tokens=2,
                max_tokens=2,
                overlap_tokens=0,
                parent_max_tokens=8,
                embedding_provider_input_limit=16,
                type_handler_versions=TYPE_HANDLER_VERSIONS,
            ),
            document_title="Malformed code provenance",
        )

    assert exc_info.value.code == "CHUNK_SPLIT_NO_PROGRESS"
    assert exc_info.value.retryable is False
