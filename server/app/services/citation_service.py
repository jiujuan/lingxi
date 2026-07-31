from sqlalchemy.orm import Session

from server.app.core.errors import forbidden, not_found
from server.app.core.permissions import AccessContext
from server.app.models.chat import ChatSession, QueryRun
from server.app.models.document import Document, DocumentStatus
from server.app.models.qa_pair import DocumentChunk, QaPair
from server.app.repositories.citation_repo import CitationRepository
from server.app.repositories.document_repo import DocumentRepository
from server.app.services.classification_path_service import ClassificationPathService


class CitationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = CitationRepository(session)
        self.classification_paths = ClassificationPathService(session)

    def get_run(self, context: AccessContext, run_public_id: str):
        run = self.repo.get_run_by_public_id(context.tenant_id, run_public_id)
        if run is None:
            raise not_found("回答运行不存在")
        self._ensure_run_visible(context, run)
        return run

    def list_citations(self, context: AccessContext, run_public_id: str) -> list[dict]:
        run = self.get_run(context, run_public_id)
        return [
            self._citation_to_dict(item, run.run_id)
            for item in self.repo.list_citations(context.tenant_id, run.id)
        ]

    def get_source(self, context: AccessContext, citation_id: str) -> dict:
        citation = self.repo.get_citation(context.tenant_id, citation_id)
        if citation is None:
            raise not_found("引用不存在")
        run = self.session.get(QueryRun, citation.run_id)
        if run is not None:
            self._ensure_run_visible(context, run)

        document = self.session.get(Document, citation.document_id) if citation.document_id else None
        is_admin = bool(context.role_codes and "SYSTEM_ADMIN" in context.role_codes)
        if document is not None and document.status != DocumentStatus.DELETED:
            authorized = DocumentRepository(self.session).get_authorized_document(
                context, document.id
            )
            if authorized is None:
                raise forbidden("当前无权查看原文详情")
        elif not is_admin:
            raise forbidden("当前无权查看原文详情")

        snapshot = citation.snapshot or {}
        snapshot_chunk_id = snapshot.get("chunkId")
        qa_pair = None
        if snapshot_chunk_id is not None:
            # Unified hybrid citations bind directly to the winning Child Chunk.
            # A snapshot is persisted data, not an authorization boundary: its
            # identity must still match the citation tenant and document before
            # any source content can be returned.
            if not isinstance(snapshot_chunk_id, str) or not snapshot_chunk_id:
                raise not_found("引用来源不存在")
            chunk = self.session.get(DocumentChunk, snapshot_chunk_id)
            if (
                chunk is None
                or chunk.tenant_id != citation.tenant_id
                or chunk.document_id != citation.document_id
            ):
                raise not_found("引用来源不存在")
        else:
            # Historical QA citations retain their original qa_pair -> chunk
            # source resolution when no unified Chunk snapshot is present.
            qa_pair = self.session.get(QaPair, citation.qa_pair_id) if citation.qa_pair_id else None
            chunk = (
                self.session.get(DocumentChunk, qa_pair.chunk_id)
                if qa_pair is not None and qa_pair.chunk_id
                else None
            )
        page_no = snapshot.get("pageNo")
        if page_no is None:
            page_no = chunk.page_start if snapshot_chunk_id is not None and chunk is not None else None
        if page_no is None and qa_pair is not None:
            page_no = qa_pair.page_no
        return {
            "citation_id": citation.id,
            "document_id": citation.document_id,
            "document_title": document.title if document is not None else snapshot.get("title"),
            "document_deleted": bool(document is None or document.status == DocumentStatus.DELETED),
            "page_no": page_no,
            "quote": citation.quote,
            "source_text": chunk.content if chunk is not None else citation.quote,
            "source_locator": chunk.source_locator if chunk is not None else {},
            "classification": self.classification_paths.for_document(
                context.tenant_id, document, snapshot
            ),
        }

    def _ensure_run_visible(self, context: AccessContext, run) -> None:
        if context.role_codes and "SYSTEM_ADMIN" in context.role_codes:
            return
        if run.session_id is None:
            raise forbidden("当前无权查看回答运行")
        chat_session = self.session.get(ChatSession, run.session_id)
        if chat_session is None or chat_session.user_id != context.user_id:
            raise forbidden("当前无权查看回答运行")

    def _citation_to_dict(self, citation, run_public_id: str) -> dict:
        document = self.session.get(Document, citation.document_id) if citation.document_id else None
        snapshot = citation.snapshot or {}
        return {
            "id": citation.id,
            "run_id": run_public_id,
            "document_id": citation.document_id,
            "qa_pair_id": citation.qa_pair_id,
            "title": document.title if document is not None else snapshot.get("title"),
            "page_no": snapshot.get("pageNo"),
            "quote": citation.quote,
            "rank": citation.rank,
            "score": float(snapshot.get("rerankScore") or snapshot.get("score") or 0),
            "classification": self.classification_paths.for_document(
                citation.tenant_id, document, snapshot
            ),
        }
