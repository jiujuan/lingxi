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
from server.app.services.chunking.overlap import (
    OverlapBlock,
    OverlapResult,
    apply_prose_overlap,
)
from server.app.services.chunking.policy import ChunkPolicy, ChunkPolicyError
from server.app.services.chunking.recursive_splitter import (
    ChunkSplitNoProgressError,
    RecursiveSplitResult,
    SplitBlock,
    SplitReason,
    split_oversized_prose,
)
from server.app.services.chunking.service import (
    ChunkingFeatureUnsupportedError,
    ChunkingService,
)
from server.app.services.chunking.tokenizer import (
    LocalTokenCounter,
    TokenCounter,
    TokenLimitError,
    TokenizerUnavailableError,
    require_token_counter,
)
from server.app.services.chunking.versions import TYPE_HANDLER_VERSIONS
from server.app.services.chunking.type_handlers import (
    TYPE_HANDLER_REGISTRY,
    ChunkDraft,
    TypeHandler,
    TypeHandlerContext,
    TypeHandlerResult,
    get_type_handler,
    handle_typed_block,
)

__all__ = [
    "AtomicBlock",
    "BlockType",
    "ChunkDraft",
    "ChunkPolicy",
    "ChunkPolicyError",
    "ChunkSplitNoProgressError",
    "ChunkingFeatureUnsupportedError",
    "ChunkingResult",
    "ChunkingService",
    "ChunkingStats",
    "ChunkingWarning",
    "ChunkLevel",
    "LocalTokenCounter",
    "MergedBlock",
    "MergeResult",
    "NormalizedChunk",
    "OverlapBlock",
    "OverlapResult",
    "RecursiveSplitResult",
    "SplitBlock",
    "SplitReason",
    "TYPE_HANDLER_REGISTRY",
    "TYPE_HANDLER_VERSIONS",
    "TokenCounter",
    "TokenLimitError",
    "TokenizerUnavailableError",
    "TypeHandler",
    "TypeHandlerContext",
    "TypeHandlerResult",
    "apply_prose_overlap",
    "get_type_handler",
    "group_by_safe_boundary",
    "handle_typed_block",
    "merge_small_blocks",
    "require_token_counter",
    "split_oversized_prose",
    "to_json_value",
]
