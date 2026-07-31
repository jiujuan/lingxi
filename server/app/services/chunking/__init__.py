"""Adaptive hierarchical chunking contracts and token budgets."""

from server.app.services.chunking.contracts import (
    AtomicBlock,
    BlockType,
    ChunkingResult,
    ChunkingStats,
    ChunkingWarning,
    ChunkLevel,
    NormalizedChunk,
    to_json_value,
)
from server.app.services.chunking.merge import (
    MergedBlock,
    MergeResult,
    group_by_safe_boundary,
    merge_small_blocks,
)
from server.app.services.chunking.policy import ChunkPolicy, ChunkPolicyError
from server.app.services.chunking.tokenizer import (
    LocalTokenCounter,
    TokenCounter,
    TokenLimitError,
    TokenizerUnavailableError,
    require_token_counter,
)

__all__ = [
    "AtomicBlock",
    "BlockType",
    "ChunkPolicy",
    "ChunkPolicyError",
    "ChunkingResult",
    "ChunkingStats",
    "ChunkingWarning",
    "ChunkLevel",
    "LocalTokenCounter",
    "MergedBlock",
    "MergeResult",
    "NormalizedChunk",
    "TokenCounter",
    "TokenLimitError",
    "TokenizerUnavailableError",
    "group_by_safe_boundary",
    "merge_small_blocks",
    "require_token_counter",
    "to_json_value",
]
