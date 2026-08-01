"""Typed contracts shared by adaptive hierarchical chunking components."""

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, NoReturn


class BlockType(StrEnum):
    TITLE = "TITLE"
    HEADING = "HEADING"
    TEXT = "TEXT"
    LIST = "LIST"
    TABLE = "TABLE"
    CODE = "CODE"
    FORMULA = "FORMULA"
    IMAGE = "IMAGE"
    QUOTE = "QUOTE"
    UNKNOWN = "UNKNOWN"


class ChunkLevel(StrEnum):
    PARENT = "PARENT"
    CHILD = "CHILD"


class _FrozenJsonMapping(Mapping[str, Any]):
    """Immutable JSON mapping backed only by recursively frozen tuples."""

    __slots__ = ("_items",)

    def __init__(self, items: tuple[tuple[str, Any], ...]) -> None:
        object.__setattr__(self, "_items", items)

    def __getitem__(self, key: str) -> Any:
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self):
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return repr(dict(self._items))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Mapping):
            return NotImplemented
        return dict(self.items()) == dict(other.items())

    def __setattr__(self, name: str, value: Any) -> NoReturn:
        raise TypeError("frozen JSON mapping is read-only")

    def __copy__(self) -> "_FrozenJsonMapping":
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> "_FrozenJsonMapping":
        memo[id(self)] = self
        return self

    def __reduce__(self):
        return (_restore_frozen_json_mapping, (_thaw_json_value(self),))


def _thaw_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json_value(item) for item in value]
    return value


def to_json_value(value: Any) -> Any:
    """Return a detached plain-dict/list representation of a JSON-safe value."""
    thawed = _thaw_json_value(value)
    try:
        json.dumps(thawed, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("value must contain only JSON-safe values") from exc
    return thawed


def _restore_frozen_json_mapping(value: dict[str, Any]) -> Mapping[str, Any]:
    return _freeze_json_mapping(value, field_name="pickled JSON mapping")


def _freeze_json_value(
    value: Any,
    *,
    field_name: str,
    container_ids: set[int],
) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} must contain only JSON-safe values")
        return value

    if isinstance(value, Mapping):
        container_id = id(value)
        if container_id in container_ids:
            raise ValueError(f"{field_name} must contain only JSON-safe values")
        container_ids.add(container_id)
        try:
            frozen: dict[str, Any] = {}
            for key, nested_value in value.items():
                if not isinstance(key, str):
                    raise ValueError(
                        f"{field_name} must contain only JSON-safe values"
                    )
                frozen[key] = _freeze_json_value(
                    nested_value,
                    field_name=field_name,
                    container_ids=container_ids,
                )
            return _FrozenJsonMapping(tuple(frozen.items()))
        finally:
            container_ids.remove(container_id)

    if isinstance(value, (list, tuple)):
        container_id = id(value)
        if container_id in container_ids:
            raise ValueError(f"{field_name} must contain only JSON-safe values")
        container_ids.add(container_id)
        try:
            return tuple(
                _freeze_json_value(
                    item,
                    field_name=field_name,
                    container_ids=container_ids,
                )
                for item in value
            )
        finally:
            container_ids.remove(container_id)

    raise ValueError(f"{field_name} must contain only JSON-safe values")


def _freeze_json_mapping(
    value: Mapping[str, Any],
    *,
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a JSON-safe mapping")
    if isinstance(value, _FrozenJsonMapping):
        return value
    frozen = _freeze_json_value(
        value,
        field_name=field_name,
        container_ids=set(),
    )
    try:
        json.dumps(_thaw_json_value(frozen), allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain only JSON-safe values") from exc
    return frozen


@dataclass(frozen=True)
class AtomicBlock:
    index: int
    content: str
    block_type: BlockType
    source_locator: Mapping[str, Any]
    page_no: int | None = None
    title_path: tuple[str, ...] = ()
    structural_id: str | None = None
    parent_structural_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("AtomicBlock content must not be empty")
        if not isinstance(self.source_locator, Mapping) or not self.source_locator:
            raise ValueError("AtomicBlock requires a non-empty source locator")
        object.__setattr__(self, "block_type", BlockType(self.block_type))
        object.__setattr__(self, "title_path", tuple(self.title_path))
        object.__setattr__(
            self,
            "source_locator",
            _freeze_json_mapping(self.source_locator, field_name="source_locator"),
        )
        object.__setattr__(
            self,
            "metadata",
            _freeze_json_mapping(self.metadata, field_name="metadata"),
        )


@dataclass(frozen=True)
class NormalizedChunk:
    local_id: str
    level: ChunkLevel
    parent_local_id: str | None
    chunk_index: int
    block_type: BlockType
    content: str
    title_path: tuple[str, ...]
    token_count: int
    page_start: int | None
    page_end: int | None
    source_locators: tuple[Mapping[str, Any], ...]
    atomic_block_indexes: tuple[int, ...]
    overlap_prefix_tokens: int
    content_hash: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        source_locators = tuple(self.source_locators)
        if not source_locators or any(
            not isinstance(locator, Mapping) or not locator
            for locator in source_locators
        ):
            raise ValueError(
                "NormalizedChunk requires non-empty source locator mappings"
            )
        frozen_locators = tuple(
            _freeze_json_mapping(locator, field_name="source locator")
            for locator in source_locators
        )
        object.__setattr__(self, "level", ChunkLevel(self.level))
        object.__setattr__(self, "block_type", BlockType(self.block_type))
        object.__setattr__(self, "title_path", tuple(self.title_path))
        object.__setattr__(self, "source_locators", frozen_locators)
        object.__setattr__(
            self,
            "atomic_block_indexes",
            tuple(self.atomic_block_indexes),
        )
        object.__setattr__(
            self,
            "metadata",
            _freeze_json_mapping(self.metadata, field_name="metadata"),
        )


@dataclass(frozen=True)
class ChunkingStats:
    input_block_count: int = 0
    parent_count: int = 0
    child_count: int = 0
    skipped_block_count: int = 0
    total_token_count: int = 0
    merge_count: int = 0
    split_count: int = 0
    oversized_count: int = 0


@dataclass(frozen=True)
class ChunkingWarning:
    code: str
    message: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "metadata",
            _freeze_json_mapping(self.metadata, field_name="metadata"),
        )


@dataclass(frozen=True)
class ChunkingResult:
    parents: tuple[NormalizedChunk, ...]
    children: tuple[NormalizedChunk, ...]
    stats: ChunkingStats
    warnings: tuple[ChunkingWarning, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "parents", tuple(self.parents))
        object.__setattr__(self, "children", tuple(self.children))
        object.__setattr__(self, "warnings", tuple(self.warnings))
