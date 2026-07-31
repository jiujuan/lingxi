"""Immutable version declarations for registered chunk type handlers."""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

TYPE_HANDLER_VERSIONS: Final = MappingProxyType(
    {
        "code": "1.0",
        "formula": "1.0",
        "image": "1.0",
        "list": "1.0",
        "table": "1.0",
    }
)

__all__ = ["TYPE_HANDLER_VERSIONS"]
