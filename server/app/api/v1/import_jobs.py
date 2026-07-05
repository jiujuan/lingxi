from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext, require_permission
from server.app.db.session import get_db
from server.app.schemas.import_job import (
    ImportJobCreateRequest,
    ImportJobFileBindRequest,
    ImportJobResponse,
)
from server.app.services.import_service import ImportService

router = APIRouter(prefix="/import-jobs", tags=["import-jobs"])


@router.post("", response_model=ImportJobResponse, status_code=status.HTTP_201_CREATED)
def create_import_job(
    payload: ImportJobCreateRequest,
    context: AccessContext = Depends(require_permission("DOCUMENT_UPLOAD")),
    db: Session = Depends(get_db),
) -> dict:
    job = ImportService(db).create_job(
        context,
        title=payload.title,
        permission=payload.permission.model_dump(by_alias=True),
        parse_options=payload.parse_options,
        processing_options=payload.processing_options,
    )
    return ImportService.job_to_dict(job)


@router.post(
    "/{job_id}/files",
    response_model=ImportJobResponse,
    status_code=status.HTTP_201_CREATED,
)
def bind_import_job_file(
    job_id: str,
    payload: ImportJobFileBindRequest,
    context: AccessContext = Depends(require_permission("DOCUMENT_UPLOAD")),
    db: Session = Depends(get_db),
) -> dict:
    job, job_file = ImportService(db).bind_file(
        context,
        job_id,
        object_key=payload.object_key,
        file_name=payload.file_name,
        mime_type=payload.mime_type,
        file_size=payload.file_size,
        checksum=payload.checksum,
        content_base64=payload.content_base64,
    )
    return ImportService.job_to_dict(job, job_file)


@router.post(
    "/{job_id}/file",
    response_model=ImportJobResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_import_job_file(
    job_id: str,
    file: UploadFile = File(...),
    object_key: str = Form(...),
    checksum: str = Form(...),
    context: AccessContext = Depends(require_permission("DOCUMENT_UPLOAD")),
    db: Session = Depends(get_db),
) -> dict:
    # Multipart upload: raw bytes streamed via form-data (no base64 bloat).
    content = file.file.read()
    job, job_file = ImportService(db).bind_file(
        context,
        job_id,
        object_key=object_key,
        file_name=file.filename or "upload",
        mime_type=file.content_type or "application/octet-stream",
        file_size=len(content),
        checksum=checksum,
        content=content,
    )
    return ImportService.job_to_dict(job, job_file)


@router.get("/{job_id}", response_model=ImportJobResponse)
def get_import_job(
    job_id: str,
    context: AccessContext = Depends(require_permission("DOCUMENT_READ")),
    db: Session = Depends(get_db),
) -> dict:
    job, job_file = ImportService(db).get_job(context, job_id)
    return ImportService.job_to_dict(job, job_file)


@router.post("/{job_id}/retries", response_model=ImportJobResponse)
def retry_import_job(
    job_id: str,
    context: AccessContext = Depends(require_permission("TASK_RETRY")),
    db: Session = Depends(get_db),
) -> dict:
    job, job_file = ImportService(db).retry_job(context, job_id)
    return ImportService.job_to_dict(job, job_file)
