from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext, require_permission
from server.app.db.session import get_db
from server.app.schemas.settings import SystemSettingsResponse
from server.app.services.settings_service import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SystemSettingsResponse)
def get_settings(
    context: AccessContext = Depends(require_permission("SETTING_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return SettingsService(db).get_settings(context)


@router.put("", response_model=SystemSettingsResponse)
def save_settings(
    payload: SystemSettingsResponse,
    context: AccessContext = Depends(require_permission("SETTING_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return SettingsService(db).save_settings(context, payload)

