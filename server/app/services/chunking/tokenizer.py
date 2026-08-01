"""Versioned token-budget interfaces and local implementations."""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Protocol, runtime_checkable

try:
    import tiktoken as _tiktoken
    import tiktoken.load as _tiktoken_load
except Exception:  # pragma: no cover - exercised through a monkeypatched module
    _tiktoken = None
    _tiktoken_load = None

_TOKENIZER_UNAVAILABLE = "CHUNK_TOKENIZER_UNAVAILABLE"
_TIKTOKEN_VERSION = "0.12.0"
_ENCODING_NAME = "cl100k_base"
_ENCODING_RESOURCE = (
    Path(__file__).resolve().parents[2]
    / "resources"
    / "tokenizers"
    / "cl100k_base.tiktoken"
)
_ENCODING_RESOURCE_SHA256 = (
    "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
)
_CL100K_PATTERN = (
    r"'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|"
    r"\p{N}{1,3}+| ?[^\s\p{L}\p{N}]++[\r\n]*+|"
    r"\s++$|\s*[\r\n]|\s+(?!\S)|\s"
)
_CL100K_SPECIAL_TOKENS = {
    "<|endoftext|>": 100257,
    "<|fim_prefix|>": 100258,
    "<|fim_middle|>": 100259,
    "<|fim_suffix|>": 100260,
    "<|endofprompt|>": 100276,
}


class TokenizerUnavailableError(RuntimeError):
    """Raised when no configured token counter can be used."""

    def __init__(self, message: str = "configured tokenizer is unavailable") -> None:
        full_message = f"{_TOKENIZER_UNAVAILABLE}: {message}"
        super().__init__(full_message)
        self.code = _TOKENIZER_UNAVAILABLE
        self.message = message
        self.retryable = True


class TokenLimitError(ValueError):
    """Raised for caller-supplied limits that cannot produce a safe split."""


@runtime_checkable
class TokenCounter(Protocol):
    """Count and split text using one stable tokenizer version."""

    name: str
    version: str

    def count(self, text: str) -> int: ...

    def split_by_token_limit(self, text: str, limit: int) -> list[str]: ...


class _TiktokenEncoding(Protocol):
    name: str

    def encode(
        self,
        text: str,
        *,
        disallowed_special: tuple[str, ...] = (),
    ) -> list[int]: ...

    def decode_single_token_bytes(self, token: int) -> bytes: ...


def _validate_token_limit(limit: int) -> None:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise TokenLimitError("token limit must be a positive integer")


@dataclass(frozen=True)
class LocalTokenCounter:
    """Exact local counter for tiktoken 0.12.0 ``cl100k_base`` tokens."""

    name: ClassVar[str] = "local-tiktoken-cl100k_base"
    version: ClassVar[str] = "tiktoken-0.12.0"
    _encoding: _TiktokenEncoding = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if _tiktoken is None or _tiktoken_load is None:
            raise TokenizerUnavailableError(
                f"tiktoken {_TIKTOKEN_VERSION} is not installed"
            )
        if getattr(_tiktoken, "__version__", None) != _TIKTOKEN_VERSION:
            raise TokenizerUnavailableError(
                f"tiktoken {_TIKTOKEN_VERSION} is required"
            )
        try:
            resource_bytes = _ENCODING_RESOURCE.read_bytes()
            canonical_bytes = resource_bytes.replace(b"\r\n", b"\n")
            if (
                hashlib.sha256(canonical_bytes).hexdigest()
                != _ENCODING_RESOURCE_SHA256
            ):
                raise ValueError("local tokenizer resource hash mismatch")
            mergeable_ranks = _tiktoken_load.load_tiktoken_bpe(
                str(_ENCODING_RESOURCE),
                expected_hash=hashlib.sha256(resource_bytes).hexdigest(),
            )
            encoding = _tiktoken.Encoding(
                name=_ENCODING_NAME,
                pat_str=_CL100K_PATTERN,
                mergeable_ranks=mergeable_ranks,
                special_tokens=_CL100K_SPECIAL_TOKENS,
            )
        except Exception as exc:
            raise TokenizerUnavailableError(
                f"local tiktoken encoding {_ENCODING_NAME} is unavailable"
            ) from exc
        if getattr(encoding, "name", None) != _ENCODING_NAME:
            raise TokenizerUnavailableError(
                f"local tiktoken encoding {_ENCODING_NAME} is unavailable"
            )
        object.__setattr__(self, "_encoding", encoding)

    def _encode(self, text: str) -> list[int]:
        try:
            return self._encoding.encode(text, disallowed_special=())
        except TokenizerUnavailableError:
            raise
        except Exception as exc:
            raise TokenizerUnavailableError(
                f"tiktoken encoding {_ENCODING_NAME} failed"
            ) from exc

    def count(self, text: str) -> int:
        return len(self._encode(text))

    def _find_safe_split_end(
        self,
        text: str,
        *,
        start: int,
        limit: int,
    ) -> int:
        """Return a verified safe boundary, conservatively if counts vary."""

        text_end = len(text)
        single_end = start + 1
        if self.count(text[start:single_end]) > limit:
            raise TokenLimitError(
                "token limit is smaller than one UTF-8-safe tokenizer unit"
            )
        if single_end == text_end:
            return single_end

        good_end = single_end
        probe_span = max(2, limit)
        bad_end: int | None = None
        while bad_end is None:
            probe_end = min(text_end, start + probe_span)
            if self.count(text[start:probe_end]) <= limit:
                good_end = probe_end
                if good_end == text_end:
                    return good_end
                probe_span *= 2
            else:
                bad_end = probe_end

        search_steps = (bad_end - good_end).bit_length()
        for _ in range(search_steps):
            if bad_end - good_end <= 1:
                break
            probe_end = good_end + ((bad_end - good_end) // 2)
            if self.count(text[start:probe_end]) <= limit:
                good_end = probe_end
            else:
                bad_end = probe_end
        return good_end

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        _validate_token_limit(limit)
        if not text:
            return []

        try:
            text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise TokenizerUnavailableError(
                "text cannot be represented as valid UTF-8"
            ) from exc

        parts: list[str] = []
        start = 0
        while start < len(text):
            end = self._find_safe_split_end(
                text,
                start=start,
                limit=limit,
            )
            part = text[start:end]
            if not part:
                raise TokenizerUnavailableError(
                    "tokenizer split failed to make progress"
                )
            parts.append(part)
            start = end

        if "".join(parts) != text:
            raise TokenizerUnavailableError(
                "tokenizer split does not round-trip the original text"
            )
        if any(not part or self.count(part) > limit for part in parts):
            raise TokenizerUnavailableError(
                "tokenizer split produced an invalid token budget"
            )
        return parts


@dataclass(frozen=True)
class _SafeTokenCounter:
    """Translate delegate outages while preserving local input errors."""

    _delegate: TokenCounter
    name: str
    version: str

    def count(self, text: str) -> int:
        try:
            return self._delegate.count(text)
        except (TokenizerUnavailableError, TokenLimitError):
            raise
        except Exception as exc:
            raise TokenizerUnavailableError(
                f"token counter {self.name}@{self.version} failed to count"
            ) from exc

    def split_by_token_limit(self, text: str, limit: int) -> list[str]:
        _validate_token_limit(limit)
        try:
            return self._delegate.split_by_token_limit(text, limit)
        except (TokenizerUnavailableError, TokenLimitError):
            raise
        except Exception as exc:
            raise TokenizerUnavailableError(
                f"token counter {self.name}@{self.version} failed to split"
            ) from exc


def _accepts_bound_call(method: object, *arguments: object) -> bool:
    if not callable(method):
        return False
    try:
        inspect.signature(method).bind(*arguments)
    except (TypeError, ValueError):
        return False
    return True


def require_token_counter(counter: object | None) -> TokenCounter:
    """Validate and safely adapt a runtime-compatible token counter."""

    if isinstance(counter, _SafeTokenCounter):
        return counter
    if getattr(counter, "_lingxi_validated_token_counter", False) is True:
        return counter  # type: ignore[return-value]

    try:
        is_protocol_compatible = (
            counter is not None and isinstance(counter, TokenCounter)
        )
        name = getattr(counter, "name", None)
        version = getattr(counter, "version", None)
        count = getattr(counter, "count", None)
        split = getattr(counter, "split_by_token_limit", None)
    except Exception as exc:
        raise TokenizerUnavailableError() from exc

    if (
        not is_protocol_compatible
        or not isinstance(name, str)
        or not name.strip()
        or not isinstance(version, str)
        or not version.strip()
        or not _accepts_bound_call(count, "text")
        or not _accepts_bound_call(split, "text", 1)
    ):
        raise TokenizerUnavailableError()

    return _SafeTokenCounter(
        _delegate=counter,
        name=name,
        version=version,
    )
