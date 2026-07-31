from __future__ import annotations

import copy
import json
import pickle
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path

import pytest

from server.app.services.chunking.contracts import AtomicBlock, BlockType
from server.app.services.chunking.policy import ChunkPolicy
from server.app.services.chunking.tokenizer import (
    LocalTokenCounter,
    TokenizerUnavailableError,
)
from server.app.services.chunking.type_handlers import (
    TYPE_HANDLER_REGISTRY,
    ChunkDraft,
    TypeHandlerContext,
    TypeHandlerResult,
    get_type_handler,
    handle_typed_block,
)

FIXTURES = Path(__file__).parent / "fixtures" / "chunking"


@dataclass(frozen=True)
class WhitespaceTokenCounter:
    name: str = "whitespace-fixture"
    version: str = "1.0"

    def count(self, text: str) -> int:
        return len(text.split())

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        words = text.split()
        return [
            " ".join(words[index : index + limit])
            for index in range(0, len(words), limit)
        ]


def policy(max_tokens: int = 25) -> ChunkPolicy:
    return ChunkPolicy(
        tokenizer_name="whitespace-fixture",
        tokenizer_version="1.0",
        min_tokens=max(2, min(8, max_tokens // 3)),
        target_tokens=max(3, min(16, max_tokens - 1)),
        max_tokens=max_tokens,
        overlap_tokens=1,
        parent_max_tokens=max_tokens * 3,
        embedding_provider_input_limit=max_tokens * 4,
        type_handler_versions={
            "table": "1.0",
            "code": "1.0",
            "image": "1.0",
            "formula": "1.0",
            "list": "1.0",
        },
    )


def atomic(
    block_type: BlockType,
    content: str,
    *,
    index: int = 1,
    page_no: int | None = 1,
    title_path: tuple[str, ...] = ("Guide", "Details"),
    parent_structural_id: str | None = "section-1",
    metadata: dict[str, object] | None = None,
    source_identity: str = "document-a",
) -> AtomicBlock:
    return AtomicBlock(
        index=index,
        content=content,
        block_type=block_type,
        source_locator={
            "block": index,
            "page": page_no,
            "selfRef": f"#/blocks/{index}",
            "sourceIdentity": source_identity,
        },
        page_no=page_no,
        title_path=title_path,
        structural_id=f"block-{index}",
        parent_structural_id=parent_structural_id,
        metadata=metadata or {},
    )


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8-sig"))


def test_table_golden_repeats_caption_header_and_tracks_rows() -> None:
    fixture = load_fixture("table_large.json")
    expected = load_fixture("table_large_expected.json")
    block = atomic(
        BlockType.TABLE,
        str(fixture["content"]),
        metadata={
            "caption": fixture["caption"],
            "header": fixture["header"],
            "rows": fixture["rows"],
            "rowStart": fixture["rowStart"],
        },
    )

    result = handle_typed_block(
        block,
        policy(25),
        WhitespaceTokenCounter(),
    )

    assert [draft.content for draft in result.drafts] == expected["contents"]
    assert [
        [draft.metadata["table"]["rowStart"], draft.metadata["table"]["rowEnd"]]
        for draft in result.drafts
    ] == expected["rowRanges"]
    assert {
        draft.metadata["table"]["headerHash"] for draft in result.drafts
    } == {expected["headerHash"]}
    assert all(draft.metadata["table"]["repeatedHeaderTokens"] > 0 for draft in result.drafts)
    assert all(draft.overlap_prefix_tokens == 0 for draft in result.drafts)
    assert result.warnings == ()


def test_table_oversized_row_uses_bounded_explicit_fallback() -> None:
    long_cell = " ".join(f"value{index}" for index in range(40))
    block = atomic(
        BlockType.TABLE,
        "oversized row",
        metadata={
            "caption": "Accounts",
            "header": ["id", "description"],
            "rows": [["A-1", long_cell]],
            "rowStart": 7,
        },
    )
    counter = WhitespaceTokenCounter()

    result = handle_typed_block(block, policy(18), counter)

    assert len(result.drafts) > 1
    assert all(draft.token_count <= 18 for draft in result.drafts)
    assert all(
        draft.metadata["table"]["rowStart"]
        == draft.metadata["table"]["rowEnd"]
        == 7
        for draft in result.drafts
    )
    assert all(
        draft.metadata["table"]["splitReason"] == "cell_recursive"
        for draft in result.drafts
    )
    assert [warning.code for warning in result.warnings] == [
        "TABLE_OVERSIZED_ROW_FALLBACK"
    ]


def test_wide_table_row_prefers_column_groups_before_fallback() -> None:
    block = atomic(
        BlockType.TABLE,
        "wide row",
        metadata={
            "caption": "Service matrix",
            "header": ["service", "owner", "region", "tier"],
            "rows": [["payments api", "platform team", "north america", "tier one"]],
            "rowStart": 11,
        },
    )

    result = handle_typed_block(block, policy(20), WhitespaceTokenCounter())

    assert len(result.drafts) == 2
    assert [draft.metadata["table"]["splitReason"] for draft in result.drafts] == [
        "column_group",
        "column_group",
    ]
    assert [
        [draft.metadata["table"]["columnStart"], draft.metadata["table"]["columnEnd"]]
        for draft in result.drafts
    ] == [[1, 2], [3, 4]]
    assert all(
        draft.metadata["table"]["rowStart"]
        == draft.metadata["table"]["rowEnd"]
        == 11
        for draft in result.drafts
    )
    assert all(draft.token_count <= 20 for draft in result.drafts)
    assert result.warnings == ()

def test_code_symbol_golden_prefers_symbols_and_preserves_signatures() -> None:
    fixture = load_fixture("code_symbols.json")
    expected = load_fixture("code_symbols_expected.json")
    block = atomic(
        BlockType.CODE,
        str(fixture["content"]),
        metadata={
            "language": fixture["language"],
            "file": fixture["file"],
            "symbols": fixture["symbols"],
        },
    )

    result = handle_typed_block(block, policy(25), WhitespaceTokenCounter())

    assert [draft.content for draft in result.drafts] == expected["contents"]
    assert [
        draft.metadata["code"]["symbolSignature"] for draft in result.drafts
    ] == expected["signatures"]
    assert [
        [draft.metadata["code"]["lineStart"], draft.metadata["code"]["lineEnd"]]
        for draft in result.drafts
    ] == expected["lineRanges"]
    assert all(draft.metadata["code"]["splitReason"] == "symbol" for draft in result.drafts)
    assert all(draft.metadata["code"]["language"] == "python" for draft in result.drafts)
    assert result.warnings == ()


def test_code_fence_is_kept_complete_when_within_budget() -> None:
    content = "```python\nprint('hello')\n```"
    block = atomic(BlockType.CODE, content, metadata={"language": "python"})

    result = handle_typed_block(block, policy(25), WhitespaceTokenCounter())

    assert [draft.content for draft in result.drafts] == [content]
    assert result.drafts[0].metadata["code"]["splitReason"] == "fence"
    assert result.warnings == ()


def test_oversized_code_fence_keeps_each_fallback_chunk_fenced() -> None:
    body = "\n".join(
        f"print('line {index} with detail')" for index in range(1, 9)
    )
    content = f"```python\n{body}\n```"
    block = atomic(BlockType.CODE, content, metadata={"language": "python"})

    result = handle_typed_block(block, policy(12), WhitespaceTokenCounter())

    assert len(result.drafts) > 1
    assert all(draft.content.startswith("```python\n") for draft in result.drafts)
    assert all(draft.content.rstrip().endswith("\n```") for draft in result.drafts)
    assert all(draft.token_count <= 12 for draft in result.drafts)
    assert [warning.code for warning in result.warnings] == ["CODE_FALLBACK_SPLIT"]

def test_code_fallback_packs_lines_before_token_splitting_long_lines() -> None:
    content = "alpha beta\ngamma delta\n\n" + " ".join(
        f"token{index}" for index in range(24)
    )
    counter = WhitespaceTokenCounter()
    block = atomic(BlockType.CODE, content, metadata={"language": "text"})

    result = handle_typed_block(block, policy(8), counter)

    assert all(draft.token_count <= 8 for draft in result.drafts)
    assert "".join(draft.content for draft in result.drafts) == content
    assert all(
        draft.metadata["code"]["splitReason"] in {"line", "token"}
        for draft in result.drafts
    )
    assert any(draft.metadata["code"]["splitReason"] == "token" for draft in result.drafts)
    assert [warning.code for warning in result.warnings] == ["CODE_FALLBACK_SPLIT"]


def test_image_combines_ordered_text_deduplicates_and_limits_neighbors() -> None:
    previous = atomic(
        BlockType.TEXT,
        "The diagram explains the request path.",
        index=0,
    )
    following = atomic(
        BlockType.TEXT,
        "Unrelated section text.",
        index=2,
        title_path=("Other",),
        parent_structural_id="section-2",
    )
    image = atomic(
        BlockType.IMAGE,
        "image placeholder",
        metadata={
            "caption": "Request path",
            "ocr": "Request   path",
            "alt": "Gateway flow",
        },
    )

    result = handle_typed_block(
        image,
        policy(40),
        WhitespaceTokenCounter(),
        context=TypeHandlerContext(
            previous=previous,
            following=following,
            source_identity="document-a",
            current_position=1,
            previous_position=0,
            following_position=2,
        ),
    )

    assert len(result.drafts) == 1
    content = result.drafts[0].content
    assert content.splitlines()[0] == "Section: Guide > Details"
    assert content.count("Request path") == 1
    assert "Alt: Gateway flow" in content
    assert "Context: The diagram explains the request path." in content
    assert "Unrelated section text" not in content
    assert result.drafts[0].atomic_block_indexes == (0, 1)
    assert result.drafts[0].source_locators == (
        previous.source_locator,
        image.source_locator,
    )
    assert result.warnings == ()


def test_image_without_caption_ocr_alt_or_neighbor_is_skipped() -> None:
    image = atomic(BlockType.IMAGE, "image placeholder", metadata={})

    result = handle_typed_block(
        image,
        policy(25),
        WhitespaceTokenCounter(),
    )

    assert result.drafts == ()
    assert [warning.code for warning in result.warnings] == [
        "IMAGE_WITHOUT_TEXT_SKIPPED"
    ]
    assert result.warnings[0].metadata["atomicBlockIndex"] == image.index


def test_formula_includes_same_section_explanation_without_prose_overlap() -> None:
    previous = atomic(
        BlockType.TEXT,
        "Where E is energy and m is mass.",
        index=0,
    )
    following = atomic(
        BlockType.TEXT,
        "This belongs elsewhere.",
        index=2,
        page_no=2,
    )
    formula = atomic(
        BlockType.FORMULA,
        "E = mc^2",
        metadata={"latex": "E = mc^2", "explanation": "Energy equivalence"},
    )

    result = handle_typed_block(
        formula,
        policy(40),
        WhitespaceTokenCounter(),
        context=TypeHandlerContext(
            previous=previous,
            following=following,
            source_identity="document-a",
            current_position=1,
            previous_position=0,
            following_position=2,
        ),
    )

    assert len(result.drafts) == 1
    content = result.drafts[0].content
    assert content.startswith("Section: Guide > Details\nFormula: E = mc^2")
    assert "Explanation: Energy equivalence" in content
    assert "Context: Where E is energy and m is mass." in content
    assert "Context: This belongs elsewhere." in content
    assert result.drafts[0].atomic_block_indexes == (0, 1, 2)
    assert result.drafts[0].overlap_prefix_tokens == 0


def test_large_list_repeats_intro_and_preserves_contiguous_item_ranges() -> None:
    items = [f"item {index} detail" for index in range(1, 7)]
    block = atomic(
        BlockType.LIST,
        "\n".join(f"- {item}" for item in items),
        metadata={"intro": "Required steps", "items": items, "itemStart": 1},
    )

    result = handle_typed_block(block, policy(10), WhitespaceTokenCounter())

    assert len(result.drafts) == 3
    assert all(draft.content.startswith("Required steps\n") for draft in result.drafts)
    assert [
        [draft.metadata["list"]["itemStart"], draft.metadata["list"]["itemEnd"]]
        for draft in result.drafts
    ] == [[1, 2], [3, 4], [5, 6]]
    assert all(draft.metadata["list"]["repeatedIntroTokens"] == 2 for draft in result.drafts)
    assert all(draft.overlap_prefix_tokens == 0 for draft in result.drafts)


def test_list_intro_from_neighbor_keeps_neighbor_provenance() -> None:
    previous = atomic(
        BlockType.TEXT,
        "Deployment checklist",
        index=0,
    )
    block = atomic(
        BlockType.LIST,
        "- build\n- verify",
        metadata={"items": ["build", "verify"]},
    )

    result = handle_typed_block(
        block,
        policy(10),
        WhitespaceTokenCounter(),
        context=TypeHandlerContext(
            previous=previous,
            source_identity="document-a",
            current_position=1,
            previous_position=0,
        ),
    )

    assert result.drafts[0].content.startswith("Deployment checklist\n")
    assert result.drafts[0].atomic_block_indexes == (0, 1)
    assert result.drafts[0].source_locators == (
        previous.source_locator,
        block.source_locator,
    )

def test_registry_exposes_only_supported_strong_and_list_types() -> None:
    assert tuple(TYPE_HANDLER_REGISTRY) == (
        BlockType.TABLE,
        BlockType.CODE,
        BlockType.IMAGE,
        BlockType.FORMULA,
        BlockType.LIST,
    )
    assert all(
        get_type_handler(block_type) is TYPE_HANDLER_REGISTRY[block_type]
        for block_type in TYPE_HANDLER_REGISTRY
    )
    with pytest.raises(ValueError, match="no content type handler"):
        get_type_handler(BlockType.TEXT)


def test_handlers_are_deterministic_pure_values_with_strict_token_limits() -> None:
    counter = WhitespaceTokenCounter()
    block = atomic(
        BlockType.LIST,
        "- alpha beta\n- gamma delta\n- epsilon zeta",
        metadata={
            "intro": "Items",
            "items": ["alpha beta", "gamma delta", "epsilon zeta"],
        },
    )

    first = handle_typed_block(block, policy(6), counter)
    second = handle_typed_block(block, policy(6), counter)

    assert first == second
    assert isinstance(first, TypeHandlerResult)
    assert all(isinstance(draft, ChunkDraft) for draft in first.drafts)
    assert all(draft.token_count == counter.count(draft.content) <= 6 for draft in first.drafts)
    assert copy.copy(first) == first
    assert copy.deepcopy(first) == first
    assert pickle.loads(pickle.dumps(first)) == first
    with pytest.raises((TypeError, FrozenInstanceError)):
        first.drafts[0].metadata["new"] = "value"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        first.drafts[0].content = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "block_type,metadata",
    [
        (BlockType.TABLE, {"header": ["h"], "rows": [["v"]]}),
        (BlockType.CODE, {"language": "text"}),
        (BlockType.IMAGE, {"caption": "caption"}),
        (BlockType.FORMULA, {"explanation": "explanation"}),
        (BlockType.LIST, {"intro": "intro", "items": ["one"]}),
    ],
)
def test_non_prose_handlers_never_apply_generic_overlap(
    block_type: BlockType,
    metadata: dict[str, object],
) -> None:
    content = {
        BlockType.TABLE: "| h |\n| --- |\n| v |",
        BlockType.CODE: "line",
        BlockType.IMAGE: "image placeholder",
        BlockType.FORMULA: "x = 1",
        BlockType.LIST: "- one",
    }[block_type]

    result = handle_typed_block(
        atomic(block_type, content, metadata=metadata),
        policy(20),
        WhitespaceTokenCounter(),
    )

    assert all(draft.overlap_prefix_tokens == 0 for draft in result.drafts)
    assert all("overlap" not in draft.metadata for draft in result.drafts)



def local_policy(max_tokens: int = 800) -> ChunkPolicy:
    return ChunkPolicy(
        tokenizer_name=LocalTokenCounter.name,
        tokenizer_version=LocalTokenCounter.version,
        min_tokens=max(2, min(200, max_tokens // 4)),
        target_tokens=max(3, min(600, max_tokens - 1)),
        max_tokens=max_tokens,
        overlap_tokens=min(80, max_tokens - 1),
        parent_max_tokens=max_tokens * 3,
        embedding_provider_input_limit=max_tokens * 4,
        type_handler_versions={
            "table": "1.0",
            "code": "1.0",
            "image": "1.0",
            "formula": "1.0",
            "list": "1.0",
        },
    )


@dataclass
class CountingTokenCounter:
    delegate: object
    calls: int = 0

    @property
    def name(self) -> str:
        return self.delegate.name  # type: ignore[attr-defined,no-any-return]

    @property
    def version(self) -> str:
        return self.delegate.version  # type: ignore[attr-defined,no-any-return]

    def count(self, text: str) -> int:
        self.calls += 1
        return self.delegate.count(text)  # type: ignore[attr-defined,no-any-return]

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        self.calls += 1
        return self.delegate.split_by_token_limit(text, limit)  # type: ignore[attr-defined,no-any-return]


def _code_source_ranges(result: TypeHandlerResult) -> list[tuple[int, int]]:
    return [
        (
            int(draft.metadata["code"]["sourceCharStart"]),
            int(draft.metadata["code"]["sourceCharEnd"]),
        )
        for draft in result.drafts
    ]


def _assert_complete_code_coverage(content: str, result: TypeHandlerResult) -> None:
    ranges = sorted(set(_code_source_ranges(result)))
    assert ranges[0][0] == 0
    assert ranges[-1][1] == len(content)
    assert all(left[1] == right[0] for left, right in zip(ranges, ranges[1:]))
    assert "".join(content[start:end] for start, end in ranges) == content


def test_table_uses_cell_recursive_split_before_explicit_fallback() -> None:
    long_cell = "First sentence. " + " ".join(f"detail{index}" for index in range(60))
    block = atomic(
        BlockType.TABLE,
        "single oversized cell",
        metadata={
            "caption": "Incident details",
            "header": ["description"],
            "rows": [[long_cell]],
            "rowStart": 13,
        },
    )

    result = handle_typed_block(block, policy(15), WhitespaceTokenCounter())

    assert len(result.drafts) > 1
    assert all(draft.token_count <= 15 for draft in result.drafts)
    assert {draft.metadata["table"]["splitReason"] for draft in result.drafts} == {
        "cell_recursive"
    }
    assert all(draft.metadata["table"]["columnStart"] == 1 for draft in result.drafts)
    assert all(draft.metadata["table"]["columnEnd"] == 1 for draft in result.drafts)
    assert [warning.code for warning in result.warnings] == [
        "TABLE_OVERSIZED_ROW_FALLBACK"
    ]
    assert result.warnings[0].metadata["stage"] == "cell_recursive"


@pytest.mark.parametrize("oversized_field", ["caption", "header", "cell"])
def test_table_long_context_and_cell_are_bounded_with_real_tokenizer(
    oversized_field: str,
) -> None:
    counter = LocalTokenCounter()
    long_text = " ".join(f"上下文{index}" for index in range(1400))
    caption = long_text if oversized_field == "caption" else "Audit table"
    header = [long_text if oversized_field == "header" else "description"]
    cell = long_text if oversized_field == "cell" else "normal value"
    block = atomic(
        BlockType.TABLE,
        "table source",
        metadata={"caption": caption, "header": header, "rows": [[cell]]},
    )

    result = handle_typed_block(block, local_policy(), counter)

    assert result.drafts
    assert all(draft.token_count == counter.count(draft.content) <= 800 for draft in result.drafts)
    assert [warning.code for warning in result.warnings] == [
        "TABLE_OVERSIZED_ROW_FALLBACK"
    ]
    assert all("degradation" in warning.metadata for warning in result.warnings)
    assert any(draft.metadata["table"].get("contextDegraded") for draft in result.drafts)


def test_table_prefix_degradation_has_bounded_tokenizer_work() -> None:
    counter = CountingTokenCounter(LocalTokenCounter())
    long_caption = " ".join(f"caption{index}" for index in range(5000))
    block = atomic(
        BlockType.TABLE,
        "table source",
        metadata={
            "caption": long_caption,
            "header": ["id", "value"],
            "rows": [["1", "small"]],
        },
    )

    result = handle_typed_block(block, local_policy(), counter)

    assert result.drafts
    assert counter.calls < 300


def test_code_partial_symbols_preserve_imports_gaps_constants_and_tail() -> None:
    fixture = load_fixture("code_symbols_partial.json")
    expected = load_fixture("code_symbols_partial_expected.json")
    content = str(fixture["content"])
    block = atomic(
        BlockType.CODE,
        content,
        metadata={
            "language": fixture["language"],
            "file": fixture["file"],
            "symbols": fixture["symbols"],
        },
    )

    result = handle_typed_block(block, policy(30), WhitespaceTokenCounter())

    assert [draft.content for draft in result.drafts] == expected["contents"]
    assert "".join(draft.content for draft in result.drafts) == content
    _assert_complete_code_coverage(content, result)
    assert [
        draft.metadata["code"]["splitReason"] for draft in result.drafts
    ] == expected["splitReasons"]
    assert [
        draft.metadata["code"]["symbolSignature"] for draft in result.drafts
    ] == expected["signatures"]
    assert [
        [draft.metadata["code"]["lineStart"], draft.metadata["code"]["lineEnd"]]
        for draft in result.drafts
    ] == expected["lineRanges"]
    assert [list(value) for value in _code_source_ranges(result)] == expected[
        "sourceCharRanges"
    ]
    assert [warning.code for warning in result.warnings] == ["CODE_FALLBACK_SPLIT"]
    assert result.warnings[0].metadata["invalidSymbolCount"] == 0
    assert result.warnings[0].metadata["gapCount"] == 3


@pytest.mark.parametrize(
    "symbols",
    [
        [{"signature": "bad", "lineStart": True, "lineEnd": 2}],
        [{"signature": "bad", "lineStart": 4, "lineEnd": 2}],
        [{"signature": "bad", "lineStart": 0, "lineEnd": 1}],
        [{"signature": "bad", "lineStart": 1, "lineEnd": 99}],
        [{"signature": "bad", "lineStart": "1", "lineEnd": 2}],
    ],
)
def test_code_malformed_symbol_ranges_fall_back_without_losing_source(
    symbols: list[dict[str, object]],
) -> None:
    content = "import os\n\nVALUE = 1\n\ndef run():\n    return VALUE\n"
    block = atomic(
        BlockType.CODE,
        content,
        metadata={"language": "python", "symbols": symbols},
    )

    result = handle_typed_block(block, policy(12), WhitespaceTokenCounter())

    _assert_complete_code_coverage(content, result)
    assert [warning.code for warning in result.warnings] == ["CODE_FALLBACK_SPLIT"]
    assert result.warnings[0].metadata["invalidSymbolCount"] == 1


def test_oversized_symbol_and_multiple_fences_use_absolute_line_ranges() -> None:
    symbol_lines = ["def run(value):"] + [f"    value += {index}" for index in range(1, 8)]
    symbol_content = "\n".join(symbol_lines)
    content = "import os\n" + symbol_content + "\nTAIL = 1\n"
    symbol_block = atomic(
        BlockType.CODE,
        content,
        metadata={
            "language": "python",
            "symbols": [
                {
                    "signature": "def run(value):",
                    "lineStart": 2,
                    "lineEnd": 9,
                }
            ],
        },
    )

    symbol_result = handle_typed_block(
        symbol_block, policy(6), WhitespaceTokenCounter()
    )

    _assert_complete_code_coverage(content, symbol_result)
    symbol_parts = [
        draft for draft in symbol_result.drafts
        if draft.metadata["code"]["symbolSignature"] == "def run(value):"
    ]
    assert symbol_parts
    assert min(draft.metadata["code"]["lineStart"] for draft in symbol_parts) == 2
    assert max(draft.metadata["code"]["lineEnd"] for draft in symbol_parts) == 9

    fenced = "before\n```python\na = 1\n```\nmiddle\n```js\nconst b = 2;\n```\nafter\n"
    fence_result = handle_typed_block(
        atomic(BlockType.CODE, fenced, metadata={"language": "mixed"}),
        policy(20),
        WhitespaceTokenCounter(),
    )

    _assert_complete_code_coverage(fenced, fence_result)
    fence_parts = [
        draft for draft in fence_result.drafts
        if draft.metadata["code"]["splitReason"] == "fence"
    ]
    assert [
        [draft.metadata["code"]["lineStart"], draft.metadata["code"]["lineEnd"]]
        for draft in fence_parts
    ] == [[2, 4], [6, 8]]


def test_code_fallback_preserves_blank_lines_newlines_and_safe_lexical_units() -> None:
    content = (
        'message = """first line\n\nsecond line"""\n'
        "template = `hello ${name} world`\n"
        "/* comment line one\n\ncomment line two */\n"
        "emoji = '汉字🙂é'\n"
    )
    block = atomic(BlockType.CODE, content, metadata={"language": "mixed"})

    result = handle_typed_block(block, policy(9), WhitespaceTokenCounter())

    _assert_complete_code_coverage(content, result)
    rendered = "".join(draft.content for draft in result.drafts)
    assert rendered == content
    protected_units = (
        '"""first line\n\nsecond line"""',
        "`hello ${name} world`",
        "/* comment line one\n\ncomment line two */",
    )
    assert all(unit in rendered for unit in protected_units)
    assert all(any(unit in draft.content for draft in result.drafts) for unit in protected_units)


def test_code_oversized_lexical_unit_and_long_prefixes_degrade_safely() -> None:
    counter = LocalTokenCounter()
    long_words = " ".join(f"值{index}" for index in range(1600))
    symbol_content = f"def {long_words}():\n    return '{long_words}'\n"
    symbol_result = handle_typed_block(
        atomic(
            BlockType.CODE,
            symbol_content,
            metadata={
                "language": "python",
                "symbols": [
                    {
                        "signature": f"def {long_words}():",
                        "lineStart": 1,
                        "lineEnd": 2,
                    }
                ],
            },
        ),
        local_policy(),
        counter,
    )
    assert all(draft.token_count <= 800 for draft in symbol_result.drafts)
    _assert_complete_code_coverage(symbol_content, symbol_result)
    assert symbol_result.warnings[0].metadata["prefixDegraded"] is True

    fence_info = " ".join(f"lang{index}" for index in range(1500))
    fenced = f"```{fence_info}\nprint('ok')\n```"
    fence_result = handle_typed_block(
        atomic(BlockType.CODE, fenced, metadata={"language": "unknown"}),
        local_policy(),
        counter,
    )
    assert all(draft.token_count <= 800 for draft in fence_result.drafts)
    _assert_complete_code_coverage(fenced, fence_result)
    assert fence_result.warnings[0].metadata["prefixDegraded"] is True



def test_non_sequence_symbol_metadata_falls_back_with_explicit_warning() -> None:
    content = "import os\nVALUE = 1\n"
    result = handle_typed_block(
        atomic(
            BlockType.CODE,
            content,
            metadata={"symbols": {"lineStart": 1, "lineEnd": 1}},
        ),
        policy(20),
        WhitespaceTokenCounter(),
    )

    _assert_complete_code_coverage(content, result)
    assert [warning.code for warning in result.warnings] == ["CODE_FALLBACK_SPLIT"]
    assert result.warnings[0].metadata["malformedSymbolMetadataCount"] == 1


def test_oversized_fence_preserves_blank_line_runs_in_rendered_parts() -> None:
    content = "```python\na = 1\n\n\n\n\n# after\n```\n"
    result = handle_typed_block(
        atomic(BlockType.CODE, content, metadata={"language": "python"}),
        policy(3),
        WhitespaceTokenCounter(),
    )

    _assert_complete_code_coverage(content, result)
    blank_run = "\n\n\n\n"
    matching = [
        draft
        for draft in result.drafts
        if content[
            int(draft.metadata["code"]["sourceCharStart"]):
            int(draft.metadata["code"]["sourceCharEnd"])
        ] == blank_run
    ]
    assert len(matching) == 1
    assert blank_run in matching[0].content

def test_formula_splits_latex_environment_by_environment_lines_first() -> None:
    formula = "\\begin{align}\n" + "\n".join(
        f"x_{{{index}}} &= y_{{{index}}} + z_{{{index}}} \\\\" for index in range(12)
    ) + "\n\\end{align}"
    result = handle_typed_block(
        atomic(BlockType.FORMULA, formula, metadata={"latex": formula}),
        policy(14),
        WhitespaceTokenCounter(),
    )

    assert len(result.drafts) > 1
    assert all(draft.token_count <= 14 for draft in result.drafts)
    assert all(
        draft.metadata["formula"]["splitReason"] in {
            "latex_environment",
            "formula_line",
        }
        for draft in result.drafts
    )
    assert not any(
        draft.metadata["formula"]["splitReason"] == "token_fallback"
        for draft in result.drafts
    )


def test_formula_allows_adjacent_same_section_explanation_across_pages() -> None:
    formula = atomic(BlockType.FORMULA, "x = 1", index=4, page_no=1)
    following = atomic(
        BlockType.TEXT,
        "The value is normalized on the next page.",
        index=5,
        page_no=2,
    )

    result = handle_typed_block(
        formula,
        policy(30),
        WhitespaceTokenCounter(),
        context=TypeHandlerContext(
            following=following,
            source_identity="document-a",
            current_position=4,
            following_position=5,
        ),
    )

    assert "The value is normalized on the next page." in result.drafts[0].content
    assert result.drafts[0].atomic_block_indexes == (4, 5)


@pytest.mark.parametrize(
    "previous_kwargs,context_kwargs",
    [
        ({"index": 0, "source_identity": "document-b"}, {"previous_position": 0}),
        ({"index": 2}, {"previous_position": 2}),
        ({"index": 3}, {"previous_position": 3}),
        ({"index": 0}, {"current_position": 9, "previous_position": 0}),
    ],
)
def test_context_rejects_cross_source_wrong_order_and_non_adjacent_neighbors(
    previous_kwargs: dict[str, object],
    context_kwargs: dict[str, object],
) -> None:
    current = atomic(BlockType.IMAGE, "image", index=1, metadata={"caption": "caption"})
    previous = atomic(BlockType.TEXT, "context", **previous_kwargs)
    kwargs = {"source_identity": "document-a", "current_position": 1, **context_kwargs}

    with pytest.raises(ValueError, match="context"):
        handle_typed_block(
            current,
            policy(20),
            WhitespaceTokenCounter(),
            context=TypeHandlerContext(previous=previous, **kwargs),
        )


def test_context_rejects_same_page_title_parent_but_different_document() -> None:
    current = atomic(BlockType.FORMULA, "x = 1", index=7, source_identity="document-a")
    previous = atomic(
        BlockType.TEXT,
        "maliciously similar context",
        index=6,
        source_identity="document-b",
    )

    with pytest.raises(ValueError, match="source identity"):
        handle_typed_block(
            current,
            policy(20),
            WhitespaceTokenCounter(),
            context=TypeHandlerContext(
                previous=previous,
                source_identity="document-a",
                current_position=7,
                previous_position=6,
            ),
        )


def test_list_long_intro_degrades_without_exceeding_real_token_budget() -> None:
    counter = LocalTokenCounter()
    intro = " ".join(f"intro{index}" for index in range(1600))
    block = atomic(
        BlockType.LIST,
        "- build\n- verify",
        metadata={"intro": intro, "items": ["build", "verify"]},
    )

    result = handle_typed_block(block, local_policy(), counter)

    assert result.drafts
    assert all(draft.token_count == counter.count(draft.content) <= 800 for draft in result.drafts)
    assert result.warnings
    assert result.warnings[0].metadata["degradation"] == "intro_standalone"
    assert any(draft.metadata["list"].get("introDegraded") for draft in result.drafts)


def _draft_kwargs() -> dict[str, object]:
    return {
        "content": "content",
        "block_type": BlockType.CODE,
        "title_path": ("Title",),
        "token_count": 1,
        "page_start": 1,
        "page_end": 1,
        "source_locators": ({"block": 1, "page": 1, "sourceIdentity": "document-a"},),
        "atomic_block_indexes": (1,),
        "token_counter": WhitespaceTokenCounter(),
    }


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"overlap_prefix_tokens": 1}, "overlap"),
        ({"overlap_prefix_tokens": 2, "token_count": 1}, "overlap"),
        ({"metadata": {"overlap": {"tokens": 1}}}, "overlap"),
    ],
)
def test_chunk_draft_rejects_contradictory_public_states(
    changes: dict[str, object],
    match: str,
) -> None:
    kwargs = {**_draft_kwargs(), **changes}
    with pytest.raises(ValueError, match=match):
        ChunkDraft(**kwargs)  # type: ignore[arg-type]


def test_chunk_draft_rejects_mismatched_token_count_with_public_counter() -> None:
    kwargs = {**_draft_kwargs(), "token_count": 2}
    with pytest.raises(ValueError, match="token_count"):
        ChunkDraft(
            **kwargs,
        )  # type: ignore[arg-type]


def test_chunk_draft_pickle_round_trip_preserves_non_overlap_invariants() -> None:
    draft = ChunkDraft(**_draft_kwargs())  # type: ignore[arg-type]

    restored = pickle.loads(pickle.dumps(draft))

    assert restored == draft
    assert restored.overlap_prefix_tokens == 0
    assert restored.unique_content == restored.content
    assert "overlap" not in restored.metadata


def test_table_unstructured_oversized_row_reaches_explicit_fallback_last() -> None:
    row = " ".join(f"raw{index}" for index in range(80))
    block = atomic(
        BlockType.TABLE,
        row,
        metadata={"caption": "Raw export", "header": "Header", "rows": [row]},
    )

    result = handle_typed_block(block, policy(12), WhitespaceTokenCounter())

    assert result.drafts
    assert all(draft.token_count <= 12 for draft in result.drafts)
    assert all(
        draft.metadata["table"]["splitReason"] == "oversized_row_fallback"
        for draft in result.drafts
    )
    assert result.warnings[0].metadata["stage"] == "explicit_fallback"


def test_oversized_triple_quoted_unit_reports_lexical_degradation() -> None:
    counter = LocalTokenCounter()
    payload = " ".join(f"payload{index}" for index in range(1600))
    content = f'blob = """{payload}"""\n'

    result = handle_typed_block(
        atomic(BlockType.CODE, content, metadata={"language": "python"}),
        local_policy(),
        counter,
    )

    _assert_complete_code_coverage(content, result)
    assert all(draft.token_count <= 800 for draft in result.drafts)
    assert result.warnings[0].metadata["lexicalDegraded"] is True

@dataclass(frozen=True)
class CodePointTokenCounter:
    name: str = "code-point-fixture"
    version: str = "1.0"

    def count(self, text: str) -> int:
        return len(text)

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        return [text[index : index + limit] for index in range(0, len(text), limit)]


def code_point_policy(max_tokens: int) -> ChunkPolicy:
    return ChunkPolicy(
        tokenizer_name="code-point-fixture",
        tokenizer_version="1.0",
        min_tokens=1,
        target_tokens=max(1, max_tokens - 1),
        max_tokens=max_tokens,
        overlap_tokens=0,
        parent_max_tokens=max_tokens * 3,
        embedding_provider_input_limit=max_tokens * 4,
        type_handler_versions={
            "table": "1.0",
            "code": "1.0",
            "image": "1.0",
            "formula": "1.0",
            "list": "1.0",
        },
    )


def _assert_no_boundary_inside(
    content: str,
    result: TypeHandlerResult,
    protected_text: str,
) -> None:
    protected_start = content.index(protected_text)
    protected_end = protected_start + len(protected_text)
    boundaries = {
        boundary
        for source_range in _code_source_ranges(result)
        for boundary in source_range
    }
    assert not any(protected_start < boundary < protected_end for boundary in boundaries)


def test_code_lexical_scanner_protects_strings_comments_escapes_and_crlf() -> None:
    quoted = '"text with escaped \\" delimiter and fake /* block */"'
    single = "'value with // fake and triple \\\"\\\"\\\" marker'"
    line_comment = '# comment with "quote" and /* fake */\r\n'
    slash_comment = '// comment with \'quote\' and ``` fake\r\n'
    content = (
        f"prefix = {quoted}\r\n"
        f"other = {single}\r\n"
        f"{line_comment}"
        f"{slash_comment}"
        "tail = 多字节\r\n"
    )
    counter = CodePointTokenCounter()

    result = handle_typed_block(
        atomic(BlockType.CODE, content, metadata={"language": "mixed"}),
        code_point_policy(70),
        counter,
    )

    _assert_complete_code_coverage(content, result)
    assert all(draft.token_count <= 70 for draft in result.drafts)
    for protected in (quoted, single, line_comment, slash_comment):
        _assert_no_boundary_inside(content, result, protected)
    assert not any(draft.metadata["code"]["lexicalDegraded"] for draft in result.drafts)


@pytest.mark.parametrize(
    "content,protected_start",
    [
        ('value = "' + ("超长内容\\\"" * 12), 8),
        ("value = r'" + ("raw\\'内容" * 12), 8),
        ("value = f\"" + ("模板{value}\\\"" * 12), 8),
        ("# " + ("comment 多字节 " * 20), 0),
        ("// " + ("comment 多字节 " * 20), 0),
    ],
)
def test_oversized_or_unclosed_lexical_units_preserve_source_and_degrade(
    content: str,
    protected_start: int,
) -> None:
    result = handle_typed_block(
        atomic(BlockType.CODE, content, metadata={"language": "mixed"}),
        code_point_policy(24),
        CodePointTokenCounter(),
    )

    _assert_complete_code_coverage(content, result)
    overlapping = [
        draft
        for draft in result.drafts
        if int(draft.metadata["code"]["sourceCharEnd"]) > protected_start
    ]
    assert len(overlapping) > 1
    assert all(draft.metadata["code"]["lexicalDegraded"] for draft in overlapping)
    assert result.warnings[0].metadata["lexicalDegraded"] is True


def _formula_source_text(result: TypeHandlerResult) -> str:
    return "".join(
        str(draft.metadata["formula"].get("sourceText") or "")
        for draft in result.drafts
    )


def test_formula_empty_environment_and_crlf_are_bounded_and_source_complete() -> None:
    formula = "\\begin{align}\r\n\r\n\\end{align}\r\n"
    result = handle_typed_block(
        atomic(BlockType.FORMULA, formula, metadata={"latex": formula}),
        code_point_policy(18),
        CodePointTokenCounter(),
    )

    assert result.drafts
    assert all(draft.content and draft.token_count <= 18 for draft in result.drafts)
    assert _formula_source_text(result) == formula


def test_formula_long_bpe_compact_environment_stays_unsplit_without_warning() -> None:
    environment_name = "environment" * 180
    formula = (
        f"\\begin{{{environment_name}}}\r\nx &= y + z\r\n"
        f"\\end{{{environment_name}}}"
    )
    counter = LocalTokenCounter()
    assert len(formula) > 800
    assert counter.count(f"Formula: {formula}") <= 800

    result = handle_typed_block(
        atomic(BlockType.FORMULA, formula, metadata={"latex": formula}),
        local_policy(),
        counter,
    )

    assert len(result.drafts) == 1
    assert result.drafts[0].token_count <= 800
    assert result.drafts[0].content.count("Formula: ") == 1
    assert result.drafts[0].metadata["formula"]["splitReason"] == "unsplit"
    assert _formula_source_text(result) == formula
    assert result.warnings == ()


def test_formula_long_single_line_uses_labeled_source_preserving_fallback() -> None:
    formula = " + ".join(f"x_{{{index}}}" for index in range(80))
    result = handle_typed_block(
        atomic(BlockType.FORMULA, formula, metadata={"latex": formula}),
        code_point_policy(32),
        CodePointTokenCounter(),
    )

    assert len(result.drafts) > 1
    assert all(draft.content.startswith("Formula: ") for draft in result.drafts)
    assert all(draft.token_count <= 32 for draft in result.drafts)
    assert _formula_source_text(result) == formula


def test_public_getter_handler_validates_cross_source_context() -> None:
    current = atomic(
        BlockType.IMAGE,
        "image",
        index=100,
        metadata={"caption": "caption"},
    )
    previous = atomic(
        BlockType.TEXT,
        "foreign context",
        index=10,
        source_identity="document-b",
    )
    handler = get_type_handler(BlockType.IMAGE)

    with pytest.raises(ValueError, match="source identity"):
        handler(
            current,
            policy(20),
            WhitespaceTokenCounter(),
            TypeHandlerContext(
                previous=previous,
                source_identity="document-a",
                current_position=5,
                previous_position=4,
            ),
        )


def test_table_cell_recursive_skips_empty_cells_without_losing_non_empty_cells() -> None:
    long_header = "header-" + ("context" * 12)
    long_cell = " ".join(f"detail{index}" for index in range(50))
    row = ["", long_cell, "", "tail-value", ""]
    result = handle_typed_block(
        atomic(
            BlockType.TABLE,
            "row with empty cells",
            metadata={
                "caption": "caption",
                "header": [long_header, "Details", "Middle", "Tail", "Last"],
                "rows": [row],
            },
        ),
        policy(12),
        WhitespaceTokenCounter(),
    )

    assert result.drafts
    assert all(draft.content and draft.token_count <= 12 for draft in result.drafts)
    cell_drafts = [
        draft
        for draft in result.drafts
        if draft.metadata["table"]["splitReason"] == "cell_recursive"
    ]
    assert {draft.metadata["table"]["columnStart"] for draft in cell_drafts} == {2, 4}
    combined = "\n".join(draft.content for draft in cell_drafts)
    assert all(token in combined for token in long_cell.split())
    assert "tail-value" in combined


def test_table_all_empty_cells_use_source_preserving_row_fallback() -> None:
    row = ["", "", "", ""]
    rendered_row = "|  |  |  |  |"
    result = handle_typed_block(
        atomic(
            BlockType.TABLE,
            rendered_row,
            metadata={
                "caption": " ".join(f"caption{index}" for index in range(30)),
                "header": ["A" * 80, "B" * 80, "C" * 80, "D" * 80],
                "rows": [row],
            },
        ),
        policy(10),
        WhitespaceTokenCounter(),
    )

    assert result.drafts
    assert all(draft.content and draft.token_count <= 10 for draft in result.drafts)
    fallback = [
        draft
        for draft in result.drafts
        if draft.metadata["table"]["splitReason"] == "oversized_row_fallback"
    ]
    assert fallback
    assert "".join(draft.content for draft in fallback) == rendered_row


def test_context_accepts_sparse_indexes_when_sequence_positions_are_adjacent() -> None:
    previous = atomic(BlockType.TEXT, "previous", index=10)
    current = atomic(BlockType.IMAGE, "image", index=100, metadata={"caption": "caption"})
    following = atomic(BlockType.TEXT, "following", index=900)

    result = handle_typed_block(
        current,
        policy(30),
        WhitespaceTokenCounter(),
        context=TypeHandlerContext(
            previous=previous,
            following=following,
            source_identity="document-a",
            current_position=5,
            previous_position=4,
            following_position=6,
        ),
    )

    assert result.drafts
    assert set(result.drafts[0].atomic_block_indexes) == {10, 100, 900}


@pytest.mark.parametrize(
    "previous_position,current_position",
    [(3, 5), (6, 5)],
)
def test_context_rejects_non_adjacent_or_reversed_sequence_positions(
    previous_position: int,
    current_position: int,
) -> None:
    previous = atomic(BlockType.TEXT, "previous", index=10)
    current = atomic(BlockType.IMAGE, "image", index=100, metadata={"caption": "caption"})

    with pytest.raises(ValueError, match="position"):
        handle_typed_block(
            current,
            policy(20),
            WhitespaceTokenCounter(),
            context=TypeHandlerContext(
                previous=previous,
                source_identity="document-a",
                current_position=current_position,
                previous_position=previous_position,
            ),
        )


def _expected_component_indexes(content: str) -> set[int]:
    expected: set[int] = {100}
    if "previous explanation" in content:
        expected.add(10)
    if "following explanation" in content:
        expected.add(900)
    return expected


def test_image_components_keep_labels_and_exact_contributing_provenance() -> None:
    previous = atomic(BlockType.TEXT, "previous explanation", index=10)
    current = atomic(
        BlockType.IMAGE,
        "image",
        index=100,
        metadata={
            "caption": "diagram",
            "ocr": " ".join(f"ocr{index}" for index in range(60)),
        },
    )
    following = atomic(BlockType.TEXT, "following explanation", index=900)

    result = handle_typed_block(
        current,
        policy(12),
        WhitespaceTokenCounter(),
        context=TypeHandlerContext(
            previous=previous,
            following=following,
            source_identity="document-a",
            current_position=5,
            previous_position=4,
            following_position=6,
        ),
    )

    assert all(draft.token_count <= 12 for draft in result.drafts)
    assert all(
        set(draft.atomic_block_indexes) == _expected_component_indexes(draft.content)
        for draft in result.drafts
    )
    assert all(
        line.startswith(("Section: ", "Caption: ", "OCR: ", "Alt: ", "Context: "))
        for draft in result.drafts
        for line in draft.content.splitlines()
    )
    assert all("OCR: " in draft.content for draft in result.drafts if "ocr" in draft.content)


def test_image_deduped_neighbor_uses_only_first_actual_locator() -> None:
    previous = atomic(BlockType.TEXT, "duplicate explanation", index=10)
    current = atomic(BlockType.IMAGE, "image", index=100)
    following = atomic(BlockType.TEXT, "duplicate explanation", index=900)

    result = handle_typed_block(
        current,
        policy(30),
        WhitespaceTokenCounter(),
        context=TypeHandlerContext(
            previous=previous,
            following=following,
            source_identity="document-a",
            current_position=5,
            previous_position=4,
            following_position=6,
        ),
    )

    context_drafts = [draft for draft in result.drafts if "duplicate explanation" in draft.content]
    assert len(context_drafts) == 1
    assert context_drafts[0].atomic_block_indexes == (10, 100)


def test_formula_long_explanation_has_source_aware_component_provenance() -> None:
    current = atomic(BlockType.FORMULA, "x = y", index=100, title_path=())
    following = atomic(
        BlockType.TEXT,
        " ".join(f"following explanation {index}" for index in range(50)),
        index=900,
        title_path=(),
    )

    result = handle_typed_block(
        current,
        policy(12),
        WhitespaceTokenCounter(),
        context=TypeHandlerContext(
            following=following,
            source_identity="document-a",
            current_position=5,
            following_position=6,
        ),
    )

    assert all(draft.token_count <= 12 for draft in result.drafts)
    formula_drafts = [draft for draft in result.drafts if "Formula:" in draft.content]
    explanation_drafts = [draft for draft in result.drafts if "Explanation:" in draft.content]
    assert formula_drafts and explanation_drafts
    assert all(draft.atomic_block_indexes == (100,) for draft in formula_drafts)
    assert all(draft.atomic_block_indexes == (900,) for draft in explanation_drafts)
    assert all(draft.content.startswith("Explanation: ") for draft in explanation_drafts)


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"source_locators": ({"block": 1, "page": 1}, {"block": 2, "page": 1})}, "align"),
        ({"atomic_block_indexes": (2, 1)}, "sorted"),
        ({"atomic_block_indexes": (1, 1), "source_locators": ({"block": 1}, {"block": 1})}, "unique"),
        ({"page_start": True, "page_end": True}, "page"),
        ({"page_start": -1, "page_end": -1}, "page"),
        ({"title_path": ("Guide", "")}, "title_path"),
        ({"source_locators": ({"block": 9, "page": 1},)}, "block"),
        ({"source_locators": ({"block": 1, "page": 9},)}, "page"),
    ],
)
def test_chunk_draft_rejects_contradictory_provenance(
    changes: dict[str, object],
    match: str,
) -> None:
    kwargs = {**_draft_kwargs(), **changes}
    with pytest.raises(ValueError, match=match):
        ChunkDraft(**kwargs)  # type: ignore[arg-type]


def test_chunk_draft_pickle_preserves_aligned_sorted_provenance() -> None:
    draft = ChunkDraft(**_draft_kwargs())  # type: ignore[arg-type]
    restored = pickle.loads(pickle.dumps(draft))

    assert restored.source_locators[0]["block"] == restored.atomic_block_indexes[0]
    assert restored.page_start == restored.source_locators[0]["page"]
    assert restored.atomic_block_indexes == tuple(sorted(set(restored.atomic_block_indexes)))


def test_table_warning_reports_context_and_explicit_fallback_stages() -> None:
    caption = " ".join(f"caption{index}" for index in range(40))
    row = " ".join(f"raw{index}" for index in range(80))
    result = handle_typed_block(
        atomic(
            BlockType.TABLE,
            row,
            metadata={"caption": caption, "header": "Header", "rows": [row]},
        ),
        policy(10),
        WhitespaceTokenCounter(),
    )

    warning = result.warnings[0]
    assert warning.code == "TABLE_OVERSIZED_ROW_FALLBACK"
    assert warning.metadata["stage"] == "explicit_fallback"
    assert set(warning.metadata["stages"]) == {"context", "explicit_fallback"}
    assert any(
        draft.metadata["table"]["splitReason"] == "context_fallback"
        for draft in result.drafts
    )
    assert any(
        draft.metadata["table"]["splitReason"] == "oversized_row_fallback"
        for draft in result.drafts
    )


def test_list_bpe_fragments_never_silently_drop_short_repeated_intro() -> None:
    counter = LocalTokenCounter()
    intro = "Required steps"
    item = " ".join(f"implementation-detail-{index}" for index in range(2400))
    result = handle_typed_block(
        atomic(
            BlockType.LIST,
            f"- {item}",
            metadata={"intro": intro, "items": [item]},
        ),
        local_policy(),
        counter,
    )

    assert len(result.drafts) > 1
    assert all(draft.token_count <= 800 for draft in result.drafts)
    item_drafts = [
        draft
        for draft in result.drafts
        if draft.metadata["list"]["splitReason"] == "item_group"
    ]
    assert item_drafts
    for draft in item_drafts:
        list_metadata = draft.metadata["list"]
        if draft.content.startswith(f"{intro}\n"):
            assert list_metadata["repeatedIntroTokens"] == counter.count(intro)
            assert list_metadata["introDegraded"] is False
        else:
            assert list_metadata["repeatedIntroTokens"] == 0
            assert list_metadata["introDegraded"] is True
    degraded = [
        draft for draft in item_drafts if draft.metadata["list"]["introDegraded"]
    ]
    if degraded:
        assert result.warnings
        assert result.warnings[0].metadata["degradation"] == "intro_fragment_fallback"


def test_image_only_context_keeps_section_order_and_image_anchor_provenance() -> None:
    previous = atomic(
        BlockType.TEXT,
        " ".join(f"neighbor-context-{index}" for index in range(80)),
        index=10,
    )
    image = AtomicBlock(
        index=100,
        content="image placeholder",
        block_type=BlockType.IMAGE,
        source_locator={
            "block": 100,
            "page": 1,
            "selfRef": "#/blocks/100",
            "sourceIdentity": "document-a",
            "bbox": [10, 20, 30, 40],
        },
        page_no=1,
        title_path=("Guide", "Details"),
        structural_id="block-100",
        parent_structural_id="section-1",
        metadata={},
    )

    result = handle_typed_block(
        image,
        policy(12),
        WhitespaceTokenCounter(),
        context=TypeHandlerContext(
            previous=previous,
            source_identity="document-a",
            current_position=5,
            previous_position=4,
        ),
    )

    assert result.drafts
    assert result.drafts[0].content.startswith("Section: Guide > Details")
    assert all("Caption:" not in draft.content for draft in result.drafts)
    assert all("OCR:" not in draft.content for draft in result.drafts)
    assert all("Alt:" not in draft.content for draft in result.drafts)
    assert all(100 in draft.atomic_block_indexes for draft in result.drafts)
    assert all(
        any(
            locator.get("block") == 100
            and locator.get("selfRef") == "#/blocks/100"
            and locator.get("page") == 1
            and locator.get("bbox") == (10, 20, 30, 40)
            for locator in draft.source_locators
        )
        for draft in result.drafts
    )
    context_drafts = [draft for draft in result.drafts if "Context:" in draft.content]
    assert context_drafts
    assert all(10 in draft.atomic_block_indexes for draft in context_drafts)


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"title_path": "Guide"}, "title_path"),
        ({"source_locators": ({"block": "1", "page": 1},)}, "block"),
        ({"source_locators": ({"block": 1.0, "page": 1},)}, "block"),
        ({"source_locators": ({"block": 1, "page": "1"},)}, "page"),
        ({"source_locators": ({"block": 1, "page": True},)}, "page"),
    ],
)
def test_chunk_draft_rejects_untyped_title_path_and_locator_fields(
    changes: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        ChunkDraft(**{**_draft_kwargs(), **changes})  # type: ignore[arg-type]


def test_chunk_draft_accepts_list_title_path_and_preserves_it_through_pickle() -> None:
    draft = ChunkDraft(
        **{**_draft_kwargs(), "title_path": ["Guide", "Details"]}
    )  # type: ignore[arg-type]
    restored = pickle.loads(pickle.dumps(draft))

    assert draft.title_path == ("Guide", "Details")
    assert restored.title_path == ("Guide", "Details")
    assert restored.source_locators[0]["block"] == 1
    assert restored.source_locators[0]["page"] == 1


def _near_budget_unicode_intro(counter: LocalTokenCounter) -> str:
    intro = " ".join(f"i{index}" for index in range(399))
    assert counter.count(f"{intro}\nx") <= 800
    assert counter.count(f"{intro}\n- \U0001F469\u6F22") > 800
    return intro


def test_list_prefix_candidate_token_limit_error_degrades_losslessly() -> None:
    counter = LocalTokenCounter()
    intro = _near_budget_unicode_intro(counter)
    item = ("\U0001F469\u6F22" * 700) + " final"
    previous = atomic(BlockType.TEXT, intro, index=10)
    current = atomic(
        BlockType.LIST,
        f"- {item}",
        index=100,
        metadata={"items": [item]},
    )

    result = handle_typed_block(
        current,
        local_policy(),
        counter,
        context=TypeHandlerContext(
            previous=previous,
            source_identity="document-a",
            current_position=5,
            previous_position=4,
        ),
    )

    item_drafts = [
        draft
        for draft in result.drafts
        if draft.metadata["list"]["splitReason"] == "item_group"
    ]
    assert len(item_drafts) > 1
    assert all(draft.token_count <= 800 for draft in item_drafts)
    bodies: list[str] = []
    for draft in item_drafts:
        has_intro = draft.content.startswith(f"{intro}\n")
        body = draft.content[len(intro) + 1 :] if has_intro else draft.content
        bodies.append(body)
        list_metadata = draft.metadata["list"]
        if has_intro:
            assert list_metadata["repeatedIntroTokens"] == counter.count(intro)
            assert list_metadata["introDegraded"] is False
            assert draft.atomic_block_indexes == (10, 100)
            assert draft.source_locators == (
                previous.source_locator,
                current.source_locator,
            )
        else:
            assert list_metadata["repeatedIntroTokens"] == 0
            assert list_metadata["introDegraded"] is True
            assert draft.atomic_block_indexes == (100,)
            assert draft.source_locators == (current.source_locator,)
    assert "".join(bodies) == f"- {item}"
    assert result.warnings
    assert result.warnings[0].metadata["degradation"] == "intro_fragment_fallback"


@dataclass(frozen=True)
class _OutageOnSplitTokenCounter:
    delegate: LocalTokenCounter = LocalTokenCounter()
    name: str = LocalTokenCounter.name
    version: str = LocalTokenCounter.version

    def count(self, text: str) -> int:
        return self.delegate.count(text)

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        raise TokenizerUnavailableError("test tokenizer outage")


def test_list_prefix_candidate_does_not_swallow_tokenizer_outage() -> None:
    counter = _OutageOnSplitTokenCounter()
    intro = _near_budget_unicode_intro(counter.delegate)
    item = "\U0001F469\u6F22" * 700

    with pytest.raises(TokenizerUnavailableError, match="test tokenizer outage"):
        handle_typed_block(
            atomic(
                BlockType.LIST,
                f"- {item}",
                metadata={"intro": intro, "items": [item]},
            ),
            local_policy(),
            counter,
        )


def test_list_previous_oversized_intro_has_exact_standalone_provenance() -> None:
    previous = atomic(
        BlockType.TEXT,
        " ".join(f"intro{index}" for index in range(12)),
        index=10,
    )
    current = atomic(
        BlockType.LIST,
        "- build\n- verify",
        index=100,
        metadata={"items": ["build", "verify"]},
    )

    result = handle_typed_block(
        current,
        policy(5),
        WhitespaceTokenCounter(),
        context=TypeHandlerContext(
            previous=previous,
            source_identity="document-a",
            current_position=5,
            previous_position=4,
        ),
    )

    intro_drafts = [
        draft
        for draft in result.drafts
        if draft.metadata["list"]["splitReason"] == "intro_fallback"
    ]
    item_drafts = [
        draft
        for draft in result.drafts
        if draft.metadata["list"]["splitReason"] == "item_group"
    ]
    assert intro_drafts and item_drafts
    assert all(draft.atomic_block_indexes == (10,) for draft in intro_drafts)
    assert all(
        draft.source_locators == (previous.source_locator,) for draft in intro_drafts
    )
    assert all(draft.atomic_block_indexes == (100,) for draft in item_drafts)
    assert all(
        draft.source_locators == (current.source_locator,) for draft in item_drafts
    )
    assert all(draft.metadata["list"]["repeatedIntroTokens"] == 0 for draft in item_drafts)
    assert all(draft.metadata["list"]["introDegraded"] is True for draft in item_drafts)


def test_list_previous_intro_repeated_drafts_have_exact_joint_provenance() -> None:
    previous = atomic(BlockType.TEXT, "Deployment checklist", index=10)
    current = atomic(
        BlockType.LIST,
        "- build\n- verify\n- release",
        index=100,
        metadata={"items": ["build", "verify", "release"]},
    )

    result = handle_typed_block(
        current,
        policy(6),
        WhitespaceTokenCounter(),
        context=TypeHandlerContext(
            previous=previous,
            source_identity="document-a",
            current_position=5,
            previous_position=4,
        ),
    )

    assert result.drafts
    assert all(
        draft.content.startswith("Deployment checklist\n")
        for draft in result.drafts
    )
    assert all(draft.atomic_block_indexes == (10, 100) for draft in result.drafts)
    assert all(
        draft.source_locators == (previous.source_locator, current.source_locator)
        for draft in result.drafts
    )
    assert all(draft.metadata["list"]["introDegraded"] is False for draft in result.drafts)
    assert result.warnings == ()


def test_list_current_intro_provenance_is_deduplicated() -> None:
    current = atomic(
        BlockType.LIST,
        "- build\n- verify",
        index=100,
        metadata={
            "intro": "Required steps",
            "items": ["build", "verify"],
        },
    )

    result = handle_typed_block(current, policy(6), WhitespaceTokenCounter())

    assert result.drafts
    assert all(draft.content.startswith("Required steps\n") for draft in result.drafts)
    assert all(draft.atomic_block_indexes == (100,) for draft in result.drafts)
    assert all(
        draft.source_locators == (current.source_locator,) for draft in result.drafts
    )


def test_chunk_draft_allows_distinct_immutable_unique_content() -> None:
    draft = ChunkDraft(
        **{**_draft_kwargs(), "unique_content": "unique"}  # type: ignore[arg-type]
    )

    restored = pickle.loads(pickle.dumps(draft))

    assert draft.content == "content"
    assert draft.unique_content == "unique"
    assert restored == draft
    with pytest.raises(FrozenInstanceError):
        draft.unique_content = "changed"  # type: ignore[misc]


def test_typed_handlers_emit_parent_unique_content_without_repeated_context() -> None:
    counter = WhitespaceTokenCounter()
    list_result = handle_typed_block(
        atomic(
            BlockType.LIST,
            "- a",
            metadata={"intro": "Steps now", "items": ["a", "b", "c", "d"]},
        ),
        policy(4),
        counter,
    )
    table_result = handle_typed_block(
        atomic(
            BlockType.TABLE,
            "table",
            metadata={
                "caption": "Quarterly",
                "header": "Name Value",
                "rows": [f"row{index} value{index} extra" for index in range(8)],
            },
        ),
        policy(12),
        counter,
    )

    assert "\n\n".join(draft.unique_content for draft in list_result.drafts).count(
        "Steps now"
    ) == 1
    table_unique = "\n\n".join(
        draft.unique_content for draft in table_result.drafts
    )
    assert table_unique.count("Quarterly") == 1
    assert table_unique.count("Name Value") == 1
    all_drafts = (*list_result.drafts, *table_result.drafts)
    assert all(
        draft.token_count == counter.count(draft.content)
        for draft in all_drafts
    )



def test_table_column_group_unique_content_deduplicates_caption_and_headers() -> None:
    block = atomic(
        BlockType.TABLE,
        "wide row",
        metadata={
            "caption": "Service matrix",
            "header": [
                "service-header",
                "owner-header",
                "region-header",
                "tier-header",
            ],
            "rows": [["payments-api", "platform-team", "north-america", "tier-one"]],
            "rowStart": 11,
        },
    )

    result = handle_typed_block(block, policy(20), WhitespaceTokenCounter())
    unique_parent = "\n\n".join(draft.unique_content for draft in result.drafts)

    assert {draft.metadata["table"]["splitReason"] for draft in result.drafts} == {
        "column_group"
    }
    assert unique_parent.count("Service matrix") == 1
    for header in (
        "service-header",
        "owner-header",
        "region-header",
        "tier-header",
    ):
        assert unique_parent.count(header) == 1
    for value in ("payments-api", "platform-team", "north-america", "tier-one"):
        assert unique_parent.count(value) == 1


def test_table_cell_recursive_unique_content_deduplicates_context_without_data_loss() -> None:
    cell_tokens = [f"cell-{index:03d}" for index in range(50)]
    long_cell = " ".join(cell_tokens)
    block = atomic(
        BlockType.TABLE,
        "single oversized cell",
        metadata={
            "caption": "Incident details",
            "header": ["description"],
            "rows": [[long_cell]],
            "rowStart": 13,
        },
    )

    result = handle_typed_block(block, policy(12), WhitespaceTokenCounter())
    unique_parent = "\n\n".join(draft.unique_content for draft in result.drafts)

    assert len(result.drafts) > 1
    assert {draft.metadata["table"]["splitReason"] for draft in result.drafts} == {
        "cell_recursive"
    }
    assert unique_parent.count("Incident details") == 1
    assert unique_parent.count("description") == 1
    parent_tokens = unique_parent.split()
    for token in cell_tokens:
        assert parent_tokens.count(token) == 1
    assert all(draft.unique_content for draft in result.drafts)
