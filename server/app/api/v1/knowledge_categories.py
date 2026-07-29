from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext, require_permission
from server.app.db.session import get_db
from server.app.schemas.common import OkResponse
from server.app.schemas.knowledge_category import (
    ClassificationDeleteConflict,
    KnowledgeCategoryCreateRequest,
    KnowledgeCategoryListResponse,
    KnowledgeCategoryStatsListResponse,
    KnowledgeCategoryResponse,
    KnowledgeCategoryUpdateRequest,
    KnowledgeSpaceCreateRequest,
    KnowledgeSpaceListResponse,
    KnowledgeSpaceStatsListResponse,
    KnowledgeSpaceResponse,
    KnowledgeSpaceUpdateRequest,
    MigrateCategoryDocumentsRequest,
    MigrateCategoryDocumentsResponse,
)
from server.app.services.knowledge_category_service import KnowledgeCategoryService

router = APIRouter(tags=["knowledge-classification"])


@router.get("/knowledge-spaces", response_model=KnowledgeSpaceListResponse)
def list_knowledge_spaces(
    context: AccessContext = Depends(require_permission("DOCUMENT_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return {"data": KnowledgeCategoryService(db).list_spaces(context)}


@router.get("/knowledge-spaces/stats", response_model=KnowledgeSpaceStatsListResponse)
def list_knowledge_space_stats(
    context: AccessContext = Depends(require_permission("DOCUMENT_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return KnowledgeCategoryService(db).list_space_stats(context)


@router.post(
    "/knowledge-spaces",
    response_model=KnowledgeSpaceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_space(
    payload: KnowledgeSpaceCreateRequest,
    context: AccessContext = Depends(require_permission("DOCUMENT_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return KnowledgeCategoryService(db).create_space(context, payload)


@router.put("/knowledge-spaces/{space_id}", response_model=KnowledgeSpaceResponse)
def update_knowledge_space(
    space_id: str,
    payload: KnowledgeSpaceUpdateRequest,
    context: AccessContext = Depends(require_permission("DOCUMENT_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return KnowledgeCategoryService(db).update_space(context, space_id, payload)


@router.delete(
    "/knowledge-spaces/{space_id}",
    response_model=OkResponse,
    responses={409: {"model": ClassificationDeleteConflict}},
)
def delete_knowledge_space(
    space_id: str,
    context: AccessContext = Depends(require_permission("DOCUMENT_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    KnowledgeCategoryService(db).delete_space(context, space_id)
    return {"ok": True}


@router.post(
    "/knowledge-spaces/{space_id}/migrate-documents",
    response_model=MigrateCategoryDocumentsResponse,
)
def migrate_knowledge_space_documents(
    space_id: str,
    payload: MigrateCategoryDocumentsRequest,
    context: AccessContext = Depends(require_permission("DOCUMENT_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return KnowledgeCategoryService(db).migrate_space_documents(
        context, space_id, payload
    )


@router.get(
    "/knowledge-categories",
    response_model=KnowledgeCategoryListResponse,
)
def list_knowledge_categories(
    space_id: str | None = Query(default=None, alias="spaceId"),
    department_id: str | None = Query(default=None, alias="departmentId"),
    context: AccessContext = Depends(require_permission("DOCUMENT_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return {
        "data": KnowledgeCategoryService(db).list_categories(
            context,
            space_id=space_id,
            department_id=department_id,
        )
    }


@router.get(
    "/knowledge-categories/stats",
    response_model=KnowledgeCategoryStatsListResponse,
)
def list_knowledge_category_stats(
    space_id: str | None = Query(default=None, alias="spaceId"),
    department_id: str | None = Query(default=None, alias="departmentId"),
    context: AccessContext = Depends(require_permission("DOCUMENT_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return KnowledgeCategoryService(db).list_category_stats(
        context,
        space_id=space_id,
        department_id=department_id,
    )


@router.post(
    "/knowledge-categories",
    response_model=KnowledgeCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_category(
    payload: KnowledgeCategoryCreateRequest,
    context: AccessContext = Depends(require_permission("DOCUMENT_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return KnowledgeCategoryService(db).create_category(context, payload)


@router.put(
    "/knowledge-categories/{category_id}",
    response_model=KnowledgeCategoryResponse,
)
def update_knowledge_category(
    category_id: str,
    payload: KnowledgeCategoryUpdateRequest,
    context: AccessContext = Depends(require_permission("DOCUMENT_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return KnowledgeCategoryService(db).update_category(context, category_id, payload)


@router.delete(
    "/knowledge-categories/{category_id}",
    response_model=OkResponse,
    responses={409: {"model": ClassificationDeleteConflict}},
)
def delete_knowledge_category(
    category_id: str,
    context: AccessContext = Depends(require_permission("DOCUMENT_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    KnowledgeCategoryService(db).delete_category(context, category_id)
    return {"ok": True}


@router.post(
    "/knowledge-categories/{category_id}/migrate-documents",
    response_model=MigrateCategoryDocumentsResponse,
)
def migrate_knowledge_category_documents(
    category_id: str,
    payload: MigrateCategoryDocumentsRequest,
    context: AccessContext = Depends(require_permission("DOCUMENT_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return KnowledgeCategoryService(db).migrate_category_documents(
        context, category_id, payload
    )
