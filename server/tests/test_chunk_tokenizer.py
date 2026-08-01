import base64
import copy
import hashlib
import json
import pickle
import random
import string
from pathlib import Path

import pytest

import server.app.services.chunking.tokenizer as tokenizer_module

from server.app.services.chunking import (
    ChunkPolicy,
    ChunkPolicyError,
    LocalTokenCounter,
    TYPE_HANDLER_VERSIONS,
    TokenCounter,
    TokenLimitError,
    TokenizerUnavailableError,
    require_token_counter,
)


def test_chunk_policy_defaults_match_the_frozen_spec() -> None:
    policy = ChunkPolicy()

    assert policy.name == "adaptive_hierarchical"
    assert policy.version == "1.0"
    assert policy.tokenizer_name == "configured-embedding-tokenizer"
    assert policy.min_tokens == 100
    assert policy.target_tokens == 450
    assert policy.max_tokens == 800
    assert policy.overlap_tokens == 64
    assert policy.parent_max_tokens == 1800
    assert policy.allow_cross_page_merge is True
    assert policy.semantic_split_enabled is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"min_tokens": 0},
        {"min_tokens": 451, "target_tokens": 450},
        {"target_tokens": 801, "max_tokens": 800},
        {"overlap_tokens": -1},
        {"overlap_tokens": 100, "min_tokens": 100},
        {"max_tokens": 801, "embedding_provider_input_limit": 800},
        {"parent_max_tokens": 799, "max_tokens": 800},
        {"type_handler_versions": {}},
        {"type_handler_versions": {"TEXT": ""}},
    ],
)
def test_chunk_policy_rejects_invalid_configuration_with_structured_error(
    overrides: dict,
) -> None:
    with pytest.raises(
        ChunkPolicyError,
        match="CHUNK_POLICY_INVALID",
    ) as exc_info:
        ChunkPolicy(**overrides)

    assert exc_info.value.code == "CHUNK_POLICY_INVALID"
    assert exc_info.value.retryable is False
    assert exc_info.value.message
    assert str(exc_info.value) == (
        f"{exc_info.value.code}: {exc_info.value.message}"
    )


def test_config_hash_is_stable_for_mapping_order_and_tracks_tokenizer_version() -> None:
    first = ChunkPolicy(
        tokenizer_name="local-tiktoken-cl100k_base",
        tokenizer_version="tiktoken-0.12.0",
        type_handler_versions={"TEXT": "2.0", "TABLE": "1.0"},
    )
    reordered = ChunkPolicy(
        tokenizer_name="local-tiktoken-cl100k_base",
        tokenizer_version="tiktoken-0.12.0",
        type_handler_versions={"TABLE": "1.0", "TEXT": "2.0"},
    )
    newer_tokenizer = ChunkPolicy(
        tokenizer_name="local-tiktoken-cl100k_base",
        tokenizer_version="tiktoken-0.13.0",
        type_handler_versions={"TEXT": "2.0", "TABLE": "1.0"},
    )

    assert first.config_hash == reordered.config_hash
    assert len(first.config_hash) == 64
    assert first.config_hash != newer_tokenizer.config_hash


def test_type_handler_versions_are_immutable_hashable_and_round_trip_safe() -> None:
    policy = ChunkPolicy(
        type_handler_versions={"TEXT": "2.0", "TABLE": "1.0"}
    )
    expected = (("TABLE", "1.0"), ("TEXT", "2.0"))

    assert policy.type_handler_versions == expected
    assert copy.copy(policy) == policy
    assert copy.deepcopy(policy) == policy
    assert pickle.loads(pickle.dumps(policy)) == policy
    assert hash(policy) == hash(copy.deepcopy(policy))

    with pytest.raises(TypeError):
        policy.type_handler_versions[0] = ("CODE", "3.0")  # type: ignore[index]


def test_type_handler_versions_have_explicit_stable_json_serialization() -> None:
    first = ChunkPolicy(
        type_handler_versions={"TEXT": "2.0", "TABLE": "1.0"}
    )
    reordered = ChunkPolicy(
        type_handler_versions={"TABLE": "1.0", "TEXT": "2.0"}
    )

    first_json = json.dumps(
        first.type_handler_versions,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    reordered_json = json.dumps(
        reordered.type_handler_versions,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    assert first_json == '[["TABLE","1.0"],["TEXT","2.0"]]'
    assert reordered_json == first_json


def test_local_counter_uses_pinned_cl100k_base_tokenizer() -> None:
    counter = LocalTokenCounter()

    assert isinstance(counter, TokenCounter)
    assert counter.name == "local-tiktoken-cl100k_base"
    assert counter.version == "tiktoken-0.12.0"

    with pytest.raises(TypeError):
        LocalTokenCounter(version="tiktoken-latest")  # type: ignore[call-arg]


# Offline fixture captured with OpenAI tiktoken==0.12.0 using
# encoding_for_model("text-embedding-3-small") -> cl100k_base. The counts are
# fixed so the production counter must exactly reproduce Provider semantics.
_PROVIDER_TOKEN_FIXTURE_SOURCE = (
    "OpenAI tiktoken==0.12.0; "
    "model=text-embedding-3-small; encoding=cl100k_base"
)
_PROVIDER_TOKEN_BENCHMARK = [
    pytest.param("", 0, id="empty-boundary"),
    pytest.param("灵犀知识库支持自适应层级分块。", 22, id="chinese"),
    pytest.param(
        "Adaptive hierarchical chunking preserves retrieval context.",
        9,
        id="english",
    ),
    pytest.param(
        "Lingxi 灵犀 uses Token budgets for RAG 检索。",
        20,
        id="mixed",
    ),
    pytest.param(
        "def add(a: int, b: int) -> int:\n    return a + b\n",
        19,
        id="code",
    ),
    pytest.param(
        "| Name | 值 |\n|---|---:|\n| tokens | 128 |",
        19,
        id="table",
    ),
    pytest.param(
        "emoji 👩🏽‍💻 café e\u0301 — 𝛑 ≠ ∞",
        20,
        id="special-unicode",
    ),
]


@pytest.mark.parametrize("text, provider_tokens", _PROVIDER_TOKEN_BENCHMARK)
def test_local_counter_exactly_matches_frozen_provider_fixture(
    text: str,
    provider_tokens: int,
) -> None:
    assert LocalTokenCounter().count(text) == provider_tokens, (
        _PROVIDER_TOKEN_FIXTURE_SOURCE
    )


def _deterministic_random_ascii(length: int) -> str:
    generator = random.Random(20260730)
    alphabet = string.ascii_letters + string.digits + string.punctuation + " \t\r\n"
    return "".join(generator.choice(alphabet) for _ in range(length))


_ADVERSARIAL_SPLIT_TEXTS = [
    pytest.param(" " * 4097, id="continuous-spaces"),
    pytest.param(("\t\r" * 1024) + "\n", id="tabs-and-carriage-returns"),
    pytest.param(
        base64.b64encode(bytes(range(256)) * 8).decode("ascii"),
        id="base64",
    ),
    pytest.param(
        "123e4567-e89b-12d3-a456-426614174000:"
        + hashlib.sha256(b"lingxi-token-boundary").hexdigest() * 32,
        id="uuid-and-hash",
    ),
    pytest.param(_deterministic_random_ascii(4096), id="random-ascii"),
    pytest.param(("👩🏽‍💻e\u0301🇨🇳" * 256), id="emoji-and-combining-unicode"),
]


@pytest.mark.parametrize("text", _ADVERSARIAL_SPLIT_TEXTS)
def test_local_counter_hard_split_is_exact_on_adversarial_text(text: str) -> None:
    counter = LocalTokenCounter()

    parts = counter.split_by_token_limit(text, limit=17)

    assert "".join(parts) == text
    assert "".join(parts).encode("utf-8") == text.encode("utf-8")
    assert parts
    assert all(parts)
    assert all("\ufffd" not in part for part in parts)
    assert all(counter.count(part) <= 17 for part in parts)


@pytest.mark.parametrize(
    ("limit", "text"),
    [
        pytest.param(800, "token " * 900, id="limit-800"),
        pytest.param(8192, "token " * 8300, id="limit-8192"),
    ],
)
def test_local_counter_hard_split_respects_large_budget_boundaries(
    limit: int,
    text: str,
) -> None:
    counter = LocalTokenCounter()
    assert counter.count(text) > limit

    parts = counter.split_by_token_limit(text, limit)

    assert "".join(parts) == text
    assert len(parts) >= 2
    assert all(parts)
    assert all(counter.count(part) <= limit for part in parts)


@pytest.mark.parametrize(
    ("text", "limit", "expected_parts"),
    [
        pytest.param(
            " 灵",
            2,
            [" ", "灵"],
            id="space-cjk-cross-token-boundary",
        ),
        pytest.param(
            "  灵",
            2,
            ["  ", "灵"],
            id="spaces-cjk-cross-token-boundary",
        ),
        pytest.param(
            " 灵🙂",
            2,
            [" ", "灵", "🙂"],
            id="space-cjk-emoji-cross-token-boundary",
        ),
    ],
)
def test_local_counter_falls_back_to_reencoded_unicode_boundaries(
    text: str,
    limit: int,
    expected_parts: list[str],
) -> None:
    counter = LocalTokenCounter()

    parts = counter.split_by_token_limit(text, limit)

    assert parts == expected_parts
    assert "".join(parts) == text
    assert "".join(parts).encode("utf-8") == text.encode("utf-8")
    assert all(parts)
    assert all("\ufffd" not in part for part in parts)
    assert all(counter.count(part) <= limit for part in parts)


def test_local_counter_handles_non_monotonic_whitespace_prefix_counts() -> None:
    counter = LocalTokenCounter()
    text = (" " * 166) + ("\n" * 40) + ((" \n") * 80)

    assert counter.count(" " * 82) == 2
    assert counter.count(" " * 83) == 1

    parts = counter.split_by_token_limit(text, limit=1)

    assert "".join(parts) == text
    assert all(parts)
    assert all(counter.count(part) <= 1 for part in parts)


def test_local_counter_split_encode_work_has_a_linear_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter = LocalTokenCounter()
    text = "灵犀边界测试" * 500
    limit = 64
    original_encode = LocalTokenCounter._encode
    stats = {"calls": 0, "input_chars": 0, "max_input_chars": 0}
    input_budget = len(text) * 20

    def tracked_encode(self: LocalTokenCounter, candidate: str) -> list[int]:
        stats["calls"] += 1
        stats["input_chars"] += len(candidate)
        stats["max_input_chars"] = max(
            stats["max_input_chars"],
            len(candidate),
        )
        assert stats["input_chars"] <= input_budget, (
            "split encoded more than the bounded cumulative input budget"
        )
        return original_encode(self, candidate)

    monkeypatch.setattr(LocalTokenCounter, "_encode", tracked_encode)

    parts = counter.split_by_token_limit(text, limit)

    assert "".join(parts) == text
    assert all(counter.count(part) <= limit for part in parts)
    assert stats["input_chars"] <= input_budget
    assert stats["max_input_chars"] <= limit * 2
    assert stats["calls"] <= (len(parts) * 16) + 4


def test_local_counter_hard_split_preserves_text_without_empty_or_oversized_parts(
) -> None:
    counter = LocalTokenCounter()
    text = "alpha 灵犀 beta\n\nend"

    parts = counter.split_by_token_limit(text, limit=7)

    assert "".join(parts) == text
    assert parts
    assert all(parts)
    assert all(counter.count(part) <= 7 for part in parts)
    assert counter.split_by_token_limit("", limit=7) == []


def test_local_token_limit_errors_are_public_and_preserved_by_safe_adapter() -> None:
    counter = require_token_counter(LocalTokenCounter())

    assert issubclass(TokenLimitError, ValueError)
    with pytest.raises(TokenLimitError, match="positive"):
        counter.split_by_token_limit("text", 0)
    with pytest.raises(TokenLimitError, match="UTF-8"):
        counter.split_by_token_limit("👩", 1)


_CL100K_RESOURCE_SHA256 = (
    "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
)
_CL100K_RESOURCE_LENGTH = 1_681_126


def _cl100k_resource_path() -> Path:
    return (
        Path(tokenizer_module.__file__).resolve().parents[2]
        / "resources"
        / "tokenizers"
        / "cl100k_base.tiktoken"
    )


def test_local_cl100k_resource_is_present_and_hash_pinned() -> None:
    resource = _cl100k_resource_path()

    assert resource.is_file()
    contents = resource.read_bytes().replace(b"\r\n", b"\n")
    assert len(contents) == _CL100K_RESOURCE_LENGTH
    assert hashlib.sha256(contents).hexdigest() == _CL100K_RESOURCE_SHA256


def test_local_counter_initializes_offline_without_tiktoken_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def reject_network_read(path: str) -> bytes:
        if "://" in path:
            raise AssertionError(f"network read attempted: {path}")
        return Path(path).read_bytes()

    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path / "empty-cache"))
    monkeypatch.delenv("DATA_GYM_CACHE_DIR", raising=False)
    monkeypatch.setattr(tokenizer_module._tiktoken, "get_encoding", None)
    monkeypatch.setattr(
        tokenizer_module._tiktoken_load,
        "read_file",
        reject_network_read,
    )

    counter = LocalTokenCounter()

    assert counter.count("灵犀知识库支持自适应层级分块。") == 22


def test_local_counter_accepts_git_crlf_checkout_of_pinned_resource(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = _cl100k_resource_path().read_bytes().replace(b"\r\n", b"\n")
    crlf_resource = tmp_path / "cl100k_base.tiktoken"
    crlf_resource.write_bytes(source.replace(b"\n", b"\r\n"))
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path / "empty-cache"))
    monkeypatch.delenv("DATA_GYM_CACHE_DIR", raising=False)
    monkeypatch.setattr(
        tokenizer_module,
        "_ENCODING_RESOURCE",
        crlf_resource,
    )

    counter = LocalTokenCounter()

    assert counter.count(" 灵") == 3


class _MissingEncodingTiktoken:
    __version__ = "0.12.0"

    @staticmethod
    def Encoding(**kwargs: object) -> object:
        raise RuntimeError(f"encoding unavailable: {kwargs.get('name')}")


class _WrongVersionTiktoken:
    __version__ = "0.11.0"

    @staticmethod
    def get_encoding(name: str) -> object:
        return object()


@pytest.mark.parametrize(
    "unavailable_tiktoken",
    [None, _MissingEncodingTiktoken(), _WrongVersionTiktoken()],
)
def test_local_counter_reports_missing_dependency_encoding_or_version(
    monkeypatch: pytest.MonkeyPatch,
    unavailable_tiktoken: object,
) -> None:
    monkeypatch.setattr(
        tokenizer_module,
        "_tiktoken",
        unavailable_tiktoken,
    )

    with pytest.raises(TokenizerUnavailableError) as exc_info:
        LocalTokenCounter()

    assert exc_info.value.code == "CHUNK_TOKENIZER_UNAVAILABLE"


def test_missing_tokenizer_raises_explicit_unavailable_error() -> None:
    with pytest.raises(
        TokenizerUnavailableError,
        match="CHUNK_TOKENIZER_UNAVAILABLE",
    ) as exc_info:
        require_token_counter(None)

    assert exc_info.value.code == "CHUNK_TOKENIZER_UNAVAILABLE"
    assert exc_info.value.retryable is True


class _IncompleteTokenCounter:
    name = "incomplete"
    version = "1.0"

    def count(self, text: str) -> int:
        return 0


@pytest.mark.parametrize("counter", [object(), _IncompleteTokenCounter()])
def test_non_token_counter_objects_raise_explicit_unavailable_error(
    counter: object,
) -> None:
    with pytest.raises(TokenizerUnavailableError) as exc_info:
        require_token_counter(counter)  # type: ignore[arg-type]

    assert exc_info.value.code == "CHUNK_TOKENIZER_UNAVAILABLE"
    assert exc_info.value.retryable is True


class _EmptyMetadataTokenCounter:
    def __init__(self, name: object, version: object) -> None:
        self.name = name
        self.version = version

    def count(self, text: str) -> int:
        return 1

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        return [text] if text else []


@pytest.mark.parametrize(
    "counter",
    [
        _EmptyMetadataTokenCounter("", "1.0"),
        _EmptyMetadataTokenCounter("counter", ""),
        _EmptyMetadataTokenCounter("   ", "1.0"),
        _EmptyMetadataTokenCounter("counter", None),
    ],
)
def test_token_counter_requires_non_empty_string_metadata(counter: object) -> None:
    with pytest.raises(TokenizerUnavailableError) as exc_info:
        require_token_counter(counter)

    assert exc_info.value.code == "CHUNK_TOKENIZER_UNAVAILABLE"


class _NonCallableTokenCounter:
    name = "non-callable"
    version = "1.0"
    count = 1
    split_by_token_limit = []


class _WrongCountSignatureTokenCounter:
    name = "wrong-count-signature"
    version = "1.0"

    def count(self) -> int:
        return 0

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        return [text]


class _WrongSplitSignatureTokenCounter:
    name = "wrong-split-signature"
    version = "1.0"

    def count(self, text: str) -> int:
        return 1

    def split_by_token_limit(self, text: str) -> list[str]:
        return [text]


@pytest.mark.parametrize(
    "counter",
    [
        _NonCallableTokenCounter(),
        _WrongCountSignatureTokenCounter(),
        _WrongSplitSignatureTokenCounter(),
    ],
)
def test_token_counter_rejects_non_callable_or_wrong_bound_signatures(
    counter: object,
) -> None:
    with pytest.raises(TokenizerUnavailableError) as exc_info:
        require_token_counter(counter)

    assert exc_info.value.code == "CHUNK_TOKENIZER_UNAVAILABLE"


class _RuntimeFailingTokenCounter:
    name = "runtime-failure"
    version = "1.0"

    def count(self, text: str) -> int:
        raise RuntimeError("provider count failed")

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        raise OSError("provider split failed")


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("count", ("text",)),
        ("split_by_token_limit", ("text", 10)),
    ],
)
def test_token_counter_runtime_failures_become_unavailable_errors(
    operation: str,
    arguments: tuple[object, ...],
) -> None:
    counter = require_token_counter(_RuntimeFailingTokenCounter())

    with pytest.raises(TokenizerUnavailableError) as exc_info:
        getattr(counter, operation)(*arguments)

    assert exc_info.value.code == "CHUNK_TOKENIZER_UNAVAILABLE"
    assert exc_info.value.retryable is True


class _RuntimeValueErrorTokenCounter:
    name = "runtime-value-error"
    version = "1.0"

    def count(self, text: str) -> int:
        raise ValueError("delegate count value error")

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        raise ValueError("delegate split value error")


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("count", ("text",)),
        ("split_by_token_limit", ("text", 10)),
    ],
)
def test_safe_token_counter_converts_delegate_value_errors(
    operation: str,
    arguments: tuple[object, ...],
) -> None:
    counter = require_token_counter(_RuntimeValueErrorTokenCounter())

    with pytest.raises(TokenizerUnavailableError) as exc_info:
        getattr(counter, operation)(*arguments)

    assert exc_info.value.code == "CHUNK_TOKENIZER_UNAVAILABLE"


def test_safe_token_counter_preserves_local_behavior_and_parameter_errors() -> None:
    local = LocalTokenCounter()
    counter = require_token_counter(local)
    text = "alpha 灵犀 beta"

    assert counter.name == local.name
    assert counter.version == local.version
    assert counter.count(text) == local.count(text)
    assert "".join(counter.split_by_token_limit(text, 5)) == text

    with pytest.raises(TokenLimitError, match="positive"):
        counter.split_by_token_limit(text, 0)


def test_safe_token_counter_validation_is_idempotent() -> None:
    counter = require_token_counter(LocalTokenCounter())

    assert require_token_counter(counter) is counter


def test_default_policy_uses_actual_exported_handler_versions() -> None:
    default = ChunkPolicy()

    assert dict(default.type_handler_versions) == dict(TYPE_HANDLER_VERSIONS)
    with pytest.raises(TypeError):
        TYPE_HANDLER_VERSIONS["table"] = "changed"  # type: ignore[index]
