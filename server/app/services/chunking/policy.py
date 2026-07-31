"""Configuration policy for adaptive hierarchical chunking."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from server.app.services.chunking.versions import TYPE_HANDLER_VERSIONS

_POLICY_ERROR = "CHUNK_POLICY_INVALID"


class ChunkPolicyError(ValueError):
    """Structured, non-retryable validation failure for chunk policies."""

    def __init__(self, message: str) -> None:
        super().__init__(f"{_POLICY_ERROR}: {message}")
        self.code = _POLICY_ERROR
        self.message = message
        self.retryable = False


@dataclass(frozen=True)
class ChunkPolicy:
    """Token budgets and versioned inputs that affect chunk construction."""

    name: str = "adaptive_hierarchical"
    version: str = "1.0"
    tokenizer_name: str = "configured-embedding-tokenizer"
    tokenizer_version: str = "1.0"
    min_tokens: int = 100
    target_tokens: int = 450
    max_tokens: int = 800
    overlap_tokens: int = 64
    parent_max_tokens: int = 1800
    embedding_provider_input_limit: int = 8192
    allow_cross_page_merge: bool = True
    semantic_split_enabled: bool = False
    type_handler_versions: Mapping[str, str] | tuple[tuple[str, str], ...] = field(
        default_factory=lambda: tuple(TYPE_HANDLER_VERSIONS.items())
    )

    def __post_init__(self) -> None:
        versioned_names = {
            "name": self.name,
            "version": self.version,
            "tokenizer_name": self.tokenizer_name,
            "tokenizer_version": self.tokenizer_version,
        }
        if any(
            not isinstance(value, str) or not value
            for value in versioned_names.values()
        ):
            raise ChunkPolicyError(
                "policy and tokenizer names/versions must be non-empty strings"
            )

        token_limits = {
            "min_tokens": self.min_tokens,
            "target_tokens": self.target_tokens,
            "max_tokens": self.max_tokens,
            "overlap_tokens": self.overlap_tokens,
            "parent_max_tokens": self.parent_max_tokens,
            "embedding_provider_input_limit": (
                self.embedding_provider_input_limit
            ),
        }
        if any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in token_limits.values()
        ):
            raise ChunkPolicyError("token limits must be integers")

        if not 0 < self.min_tokens <= self.target_tokens <= self.max_tokens:
            raise ChunkPolicyError(
                "expected 0 < min_tokens <= target_tokens <= max_tokens"
            )
        if not 0 <= self.overlap_tokens < self.min_tokens:
            raise ChunkPolicyError(
                "expected 0 <= overlap_tokens < min_tokens"
            )
        if self.max_tokens > self.embedding_provider_input_limit:
            raise ChunkPolicyError(
                "max_tokens exceeds embedding_provider_input_limit"
            )
        if self.parent_max_tokens < self.max_tokens:
            raise ChunkPolicyError(
                "parent_max_tokens must be >= max_tokens"
            )

        raw_versions = self.type_handler_versions
        if isinstance(raw_versions, Mapping):
            version_items = tuple(raw_versions.items())
        elif isinstance(raw_versions, tuple) and all(
            isinstance(item, tuple) and len(item) == 2
            for item in raw_versions
        ):
            version_items = raw_versions
        else:
            raise ChunkPolicyError(
                "type_handler_versions must be a mapping or normalized tuple"
            )

        if not version_items or any(
            not isinstance(name, str)
            or not name
            or not isinstance(version, str)
            or not version
            for name, version in version_items
        ):
            raise ChunkPolicyError(
                "type_handler_versions must contain non-empty string "
                "names and versions"
            )
        if len(dict(version_items)) != len(version_items):
            raise ChunkPolicyError(
                "type_handler_versions must not contain duplicate names"
            )

        object.__setattr__(
            self,
            "type_handler_versions",
            tuple(sorted(version_items)),
        )

    @property
    def config_hash(self) -> str:
        """Return the SHA-256 of the canonical boundary-affecting config."""

        payload = {
            "algorithm": {"name": self.name, "version": self.version},
            "parameters": {
                "allow_cross_page_merge": self.allow_cross_page_merge,
                "embedding_provider_input_limit": (
                    self.embedding_provider_input_limit
                ),
                "max_tokens": self.max_tokens,
                "min_tokens": self.min_tokens,
                "overlap_tokens": self.overlap_tokens,
                "parent_max_tokens": self.parent_max_tokens,
                "semantic_split_enabled": self.semantic_split_enabled,
                "target_tokens": self.target_tokens,
            },
            "tokenizer": {
                "name": self.tokenizer_name,
                "version": self.tokenizer_version,
            },
            "type_handler_versions": dict(self.type_handler_versions),
        }
        canonical_json = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical_json).hexdigest()
