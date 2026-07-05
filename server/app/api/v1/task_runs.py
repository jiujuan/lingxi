from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext, require_permission
from server.app.db.session import get_db
from server.app.services.task_retry_service import TaskRetryService

router = APIRouter(prefix="/task-runs", tags=["task-runs"])


class TaskRetryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    resource_id: str = Field(alias="resourceId")
    status: str
    stage: str
    retry_count: int = Field(alias="retryCount")


@router.post("/{task_run_id}/retry", response_model=TaskRetryResponse)
def retry_task_run(
    task_run_id: str,
    context: AccessContext = Depends(require_permission("TASK_RETRY")),
    db: Session = Depends(get_db),
) -> dict:
    return TaskRetryService(db).retry_task_run(context, task_run_id)

