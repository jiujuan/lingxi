"""Strict source-identity helpers shared by chunking stages."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import replace
from typing import Final

from server.app.services.chunking.contracts import AtomicBlock, to_json_value

SOURCE_IDENTITY_KEYS: Final = (
    "sourceIdentity",
    "documentId",
    "sourceId",
    "document_id",
    "source_id",
)
SOURCE_IDENTITY_METADATA_KEY: Final = "_lingxi_source_identity"


def explicit_source_identity(block: AtomicBlock) -> str | None:
    """Return one validated explicit locator identity, rejecting ambiguity."""

    values: list[str] = []
    for key in SOURCE_IDENTITY_KEYS:
        if key not in block.source_locator:
            continue
        value = block.source_locator[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"source identity field {key} must be a non-empty string"
            )
        values.append(value.strip())
    if len(set(values)) > 1:
        raise ValueError("source identity fields must not conflict")
    return values[0] if values else None


def source_identity(block: AtomicBlock) -> str | None:
    """Return the validated explicit or service-assigned source identity."""

    internal = block.metadata.get(SOURCE_IDENTITY_METADATA_KEY)
    if internal is not None:
        if not isinstance(internal, str) or not internal.strip():
            raise ValueError("internal source identity must be a non-empty string")
        return internal.strip()
    return explicit_source_identity(block)


def assign_call_source_identity(
    blocks: Sequence[AtomicBlock], *, document_title: str
) -> tuple[AtomicBlock, ...]:
    """Validate identities and assign one deterministic identity when all are absent."""

    explicit: list[str | None] = []
    for block in blocks:
        if SOURCE_IDENTITY_METADATA_KEY in block.metadata:
            raise ValueError(
                f"AtomicBlock metadata reserves {SOURCE_IDENTITY_METADATA_KEY}"
            )
        explicit.append(explicit_source_identity(block))

    present = sum(value is not None for value in explicit)
    if present and present != len(blocks):
        raise ValueError(
            "source identity must be explicit for every block or absent for every block"
        )
    if present:
        return tuple(blocks)

    payload = {
        "document_title": document_title,
        "blocks": [
            {
                "index": block.index,
                "content": block.content,
                "block_type": block.block_type.value,
                "page_no": block.page_no,
                "title_path": block.title_path,
                "source_locator": to_json_value(block.source_locator),
                "structural_id": block.structural_id,
                "parent_structural_id": block.parent_structural_id,
                "metadata": to_json_value(block.metadata),
            }
            for block in blocks
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    call_identity = "call:" + hashlib.sha256(canonical).hexdigest()
    return tuple(
        replace(
            block,
            metadata={
                **to_json_value(block.metadata),
                SOURCE_IDENTITY_METADATA_KEY: call_identity,
            },
        )
        for block in blocks
    )


__all__ = [
    "SOURCE_IDENTITY_KEYS",
    "SOURCE_IDENTITY_METADATA_KEY",
    "assign_call_source_identity",
    "explicit_source_identity",
    "source_identity",
]
