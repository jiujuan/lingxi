"""Scope-safe parent/neighbor context hydration for hierarchical retrieval."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext
from server.app.models.document import Document
from server.app.models.qa_pair import DocumentChunk
from server.app.repositories.retrieval_repo import RetrievalRepository
from server.app.schemas.retrieval import RetrievalAccessScope, RetrievalCandidate
from server.app.services.chunking.tokenizer import LocalTokenCounter, TokenCounter


@dataclass(frozen=True)
class HydratedContextSegment:
    """Supplemental context that is never a standalone citation target."""

    kind: str
    content: str
    parent_chunk_id: str | None
    child_chunk_id: str
    context_chunk_id: str | None = None


class ContextHydrationService:
    """Load authorized Parent/Neighbor context around retrieved Child evidence.

    The candidate is still the exact Child evidence.  Parent and neighboring
    Child text is attached only as supplemental prompt context, so citations
    continue to resolve through the winning Child ``chunk_id``.
    """

    def __init__(
        self,
        session: Session,
        *,
        token_counter: TokenCounter | None = None,
        neighbor_window: int = 1,
        parent_max_tokens_per_hit: int = 1200,
    ) -> None:
        if neighbor_window < 0:
            raise ValueError("neighbor_window must be non-negative")
        if parent_max_tokens_per_hit <= 0:
            raise ValueError("parent_max_tokens_per_hit must be positive")
        self.session = session
        self.repo = RetrievalRepository(session)
        self.token_counter = token_counter or LocalTokenCounter()
        self.neighbor_window = neighbor_window
        self.parent_max_tokens_per_hit = parent_max_tokens_per_hit

    def hydrate(
        self,
        context: AccessContext,
        candidates: list[RetrievalCandidate],
        access_scope: RetrievalAccessScope | None = None,
    ) -> list[RetrievalCandidate]:
        """Attach scope-checked supplemental segments to Child candidates.

        Every row used for hydration is fetched through the same tenant, ACL,
        classification, READY-document, soft-delete, ACTIVE-level boundary as
        retrieval.  In particular, this method never uses ``Session.get`` or
        an ``id``-only query for a Parent/Neighbor.
        """
        if not candidates:
            return candidates

        source_children = self._load_scoped_source_children(
            context, candidates, access_scope
        )
        parents = self._load_scoped_parents(context, source_children.values(), access_scope)
        neighbors = self._load_scoped_neighbors(
            context, source_children.values(), access_scope
        )

        segments_by_candidate: dict[int, list[HydratedContextSegment]] = {
            id(candidate): [] for candidate in candidates
        }
        # Child evidence has the highest priority.  Seed de-duplication with
        # every returned Child before adding any Parent/Neighbor content.
        seen_content = {
            self._normalise(candidate.content or candidate.answer)
            for candidate in candidates
            if self._normalise(candidate.content or candidate.answer)
        }
        ordered = sorted(
            enumerate(candidates),
            key=lambda item: (-self._candidate_score(item[1]), item[0]),
        )
        for _, candidate in ordered:
            source = source_children.get((candidate.chunk_id, candidate.document_id))
            if source is None:
                continue

            parent = parents.get(source.parent_chunk_id) if source.parent_chunk_id else None
            if parent is not None and parent.document_id != source.document_id:
                # A malformed relationship must not cross a document boundary,
                # even when both documents are independently authorized.
                parent = None
            if parent is not None:
                parent_text = self._parent_context_window(parent.content, source.content)
                self._append_if_incremental(
                    segments_by_candidate[id(candidate)],
                    seen_content,
                    HydratedContextSegment(
                        kind="PARENT",
                        content=parent_text,
                        parent_chunk_id=parent.id,
                        child_chunk_id=source.id,
                        context_chunk_id=parent.id,
                    ),
                )

            for neighbor in neighbors.get(source.id, ()):
                if neighbor.id == source.id:
                    continue
                self._append_if_incremental(
                    segments_by_candidate[id(candidate)],
                    seen_content,
                    HydratedContextSegment(
                        kind="NEIGHBOR",
                        content=neighbor.content,
                        parent_chunk_id=neighbor.parent_chunk_id,
                        child_chunk_id=source.id,
                        context_chunk_id=neighbor.id,
                    ),
                )

        # Do not expose partially hydrated state if any select/build above
        # fails: assignment happens only after all work has succeeded.
        for candidate in candidates:
            candidate._lingxi_context_segments = tuple(segments_by_candidate[id(candidate)])
        return candidates

    def _load_scoped_source_children(
        self,
        context: AccessContext,
        candidates: Iterable[RetrievalCandidate],
        access_scope: RetrievalAccessScope | None,
    ) -> dict[tuple[str, str], DocumentChunk]:
        requested = {
            (candidate.chunk_id, candidate.document_id)
            for candidate in candidates
            if candidate.chunk_id and candidate.document_id
        }
        if not requested:
            return {}
        chunk_ids = {chunk_id for chunk_id, _ in requested}
        statement = (
            select(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                *self.repo._access_scope_filters(context, access_scope, DocumentChunk),
                DocumentChunk.id.in_(chunk_ids),
                DocumentChunk.status == "ACTIVE",
                DocumentChunk.chunk_level == "CHILD",
                self.repo._source_parent_is_valid(),
            )
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index, DocumentChunk.id)
        )
        return {
            (chunk.id, chunk.document_id): chunk
            for chunk in self.session.scalars(statement).unique().all()
            if (chunk.id, chunk.document_id) in requested
        }

    def _load_scoped_parents(
        self,
        context: AccessContext,
        source_children: Iterable[DocumentChunk],
        access_scope: RetrievalAccessScope | None,
    ) -> dict[str, DocumentChunk]:
        parent_ids = {child.parent_chunk_id for child in source_children if child.parent_chunk_id}
        if not parent_ids:
            return {}
        statement = (
            select(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                *self.repo._access_scope_filters(context, access_scope, DocumentChunk),
                DocumentChunk.id.in_(parent_ids),
                DocumentChunk.status == "ACTIVE",
                DocumentChunk.chunk_level == "PARENT",
            )
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index, DocumentChunk.id)
        )
        return {chunk.id: chunk for chunk in self.session.scalars(statement).unique().all()}

    def _load_scoped_neighbors(
        self,
        context: AccessContext,
        source_children: Iterable[DocumentChunk],
        access_scope: RetrievalAccessScope | None,
    ) -> dict[str, tuple[DocumentChunk, ...]]:
        """Return a separate authorized neighbor window for every source Child."""
        source_list = [child for child in source_children if child.parent_chunk_id]
        if not source_list or self.neighbor_window == 0:
            return {}

        # Push every source Child's complete relationship/range boundary into
        # SQL. This prevents loading all CHILD rows for a Parent merely to
        # discard distant rows in Python.
        source_windows = [
            and_(
                DocumentChunk.parent_chunk_id == source.parent_chunk_id,
                DocumentChunk.document_id == source.document_id,
                DocumentChunk.chunk_index >= source.chunk_index - self.neighbor_window,
                DocumentChunk.chunk_index <= source.chunk_index + self.neighbor_window,
            )
            for source in source_list
        ]
        statement = (
            select(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                *self.repo._access_scope_filters(context, access_scope, DocumentChunk),
                or_(*source_windows),
                DocumentChunk.status == "ACTIVE",
                DocumentChunk.chunk_level == "CHILD",
                self.repo._source_parent_is_valid(),
            )
            .order_by(
                DocumentChunk.parent_chunk_id,
                DocumentChunk.chunk_index,
                DocumentChunk.id,
            )
        )

        # The coordinate index preserves results per source Child without the
        # former source-by-all-authorized-children nested scan. Its work is
        # bounded by the requested windows, not by every Child of a Parent.
        source_ids_by_neighbor_coordinate: dict[tuple[str, str, int], list[str]] = {}
        for source in source_list:
            for chunk_index in range(
                source.chunk_index - self.neighbor_window,
                source.chunk_index + self.neighbor_window + 1,
            ):
                key = (source.parent_chunk_id, source.document_id, chunk_index)
                source_ids_by_neighbor_coordinate.setdefault(key, []).append(source.id)

        grouped: dict[str, list[DocumentChunk]] = {
            source.id: [] for source in source_list
        }
        for neighbor in self.session.scalars(statement).unique().all():
            key = (neighbor.parent_chunk_id, neighbor.document_id, neighbor.chunk_index)
            for source_id in source_ids_by_neighbor_coordinate.get(key, ()):
                grouped[source_id].append(neighbor)
        return {source_id: tuple(items) for source_id, items in grouped.items()}

    def _parent_context_window(self, parent_text: str, child_text: str) -> str:
        """Return a token-safe window around, but excluding, Child evidence.

        The Child's whitespace-tolerant span is located before selecting context.
        Each side is then truncated exclusively through ``TokenCounter`` splits,
        so a Child crossing a split boundary cannot cause a fallback to the
        beginning of the Parent.
        """
        child_span = self._child_span(parent_text, child_text)
        if child_span is None:
            return ""
        left = parent_text[: child_span.start()]
        right = parent_text[child_span.end() :]
        return self._centered_token_window(left, right)

    @staticmethod
    def _child_span(parent_text: str, child_text: str):
        child_terms = child_text.split()
        if not parent_text or not child_terms:
            return None
        whitespace_tolerant_child = r"\s+".join(
            re.escape(term) for term in child_terms
        )
        return re.search(whitespace_tolerant_child, parent_text)

    def _centered_token_window(self, left: str, right: str) -> str:
        """Fit Parent prefixes/suffixes nearest the Child within the budget."""
        budget = self.parent_max_tokens_per_hit
        center_left_budget = budget // 2
        allocations = [(center_left_budget, budget - center_left_budget)]
        for distance in range(1, budget + 1):
            lower = center_left_budget - distance
            higher = center_left_budget + distance
            if lower >= 0:
                allocations.append((lower, budget - lower))
            if higher <= budget:
                allocations.append((higher, budget - higher))

        for left_budget, right_budget in allocations:
            left_context = self._token_safe_suffix(left, left_budget)
            right_context = self._token_safe_prefix(right, right_budget)
            window = self._normalise(f"{left_context} {right_context}")
            if window and self.token_counter.count(window) <= budget:
                return window
        return ""

    def _token_safe_prefix(self, text: str, budget: int) -> str:
        if not text or budget <= 0:
            return ""
        return self.token_counter.split_by_token_limit(text, budget)[0]

    def _token_safe_suffix(self, text: str, budget: int) -> str:
        if not text or budget <= 0:
            return ""
        return self.token_counter.split_by_token_limit(text, budget)[-1]

    def _append_if_incremental(
        self,
        target: list[HydratedContextSegment],
        seen_content: set[str],
        segment: HydratedContextSegment,
    ) -> None:
        normalised = self._normalise(segment.content)
        if not normalised:
            return
        # The exact/containment check prevents parent and neighbor overlap from
        # consuming context budget when the information is already represented.
        if any(
            normalised == seen
            or normalised in seen
            or seen in normalised
            for seen in seen_content
        ):
            return
        if self.token_counter.count(segment.content) <= 0:
            return
        target.append(segment)
        seen_content.add(normalised)

    @staticmethod
    def _candidate_score(candidate: RetrievalCandidate) -> float:
        return candidate.fused_score or candidate.rerank_score or candidate.rrf_score

    @staticmethod
    def _normalise(text: str | None) -> str:
        return " ".join((text or "").split())
