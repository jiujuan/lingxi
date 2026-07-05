from math import ceil
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from server.app.core.errors import not_found
from server.app.core.permissions import AccessContext, require_permission
from server.app.db.session import get_db
from server.app.models.document import Document
from server.app.models.qa_pair import QaPair
from server.app.repositories.document_repo import DocumentRepository
from server.app.repositories.qa_pair_repo import QaPairRepository
from server.app.schemas.document import (
    DocumentChunkListResponse,
    DocumentDeleteResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentPermissionRequest,
    DocumentPermissionResponse,
)
from server.app.schemas.qa_pair import QaPairListResponse, QaRegenerationResponse
from server.app.services.document_center_service import DocumentCenterService
from server.app.services.qa_split_service import QaSplitService

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=DocumentListResponse)
def list_documents(
    keyword: str | None = Query(default=None, min_length=1),
    file_type: str | None = Query(default=None, alias="fileType"),
    status: str | None = Query(default=None),
    department_id: str | None = Query(default=None, alias="departmentId"),
    role_id: str | None = Query(default=None, alias="roleId"),
    updated_after: datetime | None = Query(default=None, alias="updatedAfter"),
    updated_before: datetime | None = Query(default=None, alias="updatedBefore"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    context: AccessContext = Depends(require_permission("DOCUMENT_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return DocumentCenterService(db).list_documents(
        context,
        keyword=keyword,
        file_type=file_type,
        status=status,
        department_id=department_id,
        role_id=role_id,
        updated_after=updated_after,
        updated_before=updated_before,
        page=page,
        page_size=page_size,
    )


@router.get("/{document_id}/chunks", response_model=DocumentChunkListResponse)
def list_document_chunks(
    document_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    context: AccessContext = Depends(require_permission("DOCUMENT_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return DocumentCenterService(db).list_chunks(context, document_id, page, page_size)


@router.get("/{document_id}/qa-pairs", response_model=QaPairListResponse)
def list_document_qa_pairs(
    document_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    context: AccessContext = Depends(require_permission("QA_PAIR_READ")),
    db: Session = Depends(get_db),
) -> dict:
    document = _get_document(db, context, document_id)
    items, total = QaPairRepository(db).list_by_document_page(
        context.tenant_id, document.id, page, page_size
    )
    return {
        "data": [_qa_pair_to_dict(item) for item in items],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total,
            "total_pages": ceil(total / page_size) if total else 0,
        },
    }


@router.post(
    "/{document_id}/qa-regenerations", response_model=QaRegenerationResponse
)
def regenerate_document_qa_pairs(
    document_id: str,
    context: AccessContext = Depends(require_permission("QA_PAIR_REGENERATE")),
    db: Session = Depends(get_db),
) -> dict:
    _get_document(db, context, document_id)
    job = QaSplitService(db).regenerate_document(context.tenant_id, document_id)
    return {
        "id": job.id,
        "document_id": job.document_id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "error_code": job.error_code,
        "error_message": job.error_message,
    }


@router.patch(
    "/{document_id}/permissions", response_model=DocumentPermissionResponse
)
def update_document_permissions(
    document_id: str,
    payload: DocumentPermissionRequest,
    context: AccessContext = Depends(require_permission("DOCUMENT_PERMISSION_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return DocumentCenterService(db).update_permissions(
        context, document_id, payload.model_dump(by_alias=True)
    )


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
def delete_document(
    document_id: str,
    context: AccessContext = Depends(require_permission("DOCUMENT_DELETE")),
    db: Session = Depends(get_db),
) -> dict:
    return DocumentCenterService(db).delete_document(context, document_id)


@router.get("/{document_id}", response_model=DocumentDetailResponse)
def get_document(
    document_id: str,
    context: AccessContext = Depends(require_permission("DOCUMENT_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return DocumentCenterService(db).get_document(context, document_id)


def _get_document(db: Session, context: AccessContext, document_id: str) -> Document:
    document = DocumentRepository(db).get_authorized_document(context, document_id)
    if document is None:
        raise not_found("文档不存在")
    return document


def _qa_pair_to_dict(item: QaPair) -> dict:
    return {
        "id": item.id,
        "document_id": item.document_id,
        "chunk_id": item.chunk_id,
        "question": item.question,
        "answer": item.answer,
        "quote": item.quote,
        "page_no": item.page_no,
        "embedding_status": "READY" if item.question_embedding else item.status,
        "status": item.status,
    }
