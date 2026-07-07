from sqlalchemy.orm import Session

from server.app.core.config import settings
from server.app.core.ids import current_request_id
from server.app.core.permissions import AccessContext
from server.app.integrations.parsers.registry import allowed_upload_extensions
from server.app.models.logs import AuditLog
from server.app.repositories.system_setting_repo import SystemSettingRepository
from server.app.schemas.settings import SystemSettingsResponse


SETTINGS_KEY = "v1_1_system_settings"


class SettingsService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = SystemSettingRepository(session)

    def get_settings(self, context: AccessContext) -> dict:
        setting = self.repo.get(context.tenant_id, SETTINGS_KEY)
        return setting.value if setting is not None else self.default_settings()

    def save_settings(self, context: AccessContext, payload: SystemSettingsResponse) -> dict:
        before = self.get_settings(context)
        value = payload.model_dump(by_alias=True)
        value["effectiveScopes"] = self.effective_scopes()
        setting = self.repo.upsert(context.tenant_id, SETTINGS_KEY, value)
        self.session.add(
            AuditLog(
                tenant_id=context.tenant_id,
                actor_id=context.user_id,
                action="SYSTEM_SETTINGS_UPDATED",
                resource_type="SYSTEM_SETTING",
                resource_id=setting.id,
                before_snapshot=before,
                after_snapshot=value,
                request_id=current_request_id(),
            )
        )
        self.session.commit()
        return value

    @staticmethod
    def default_settings() -> dict:
        return {
            "filePolicy": {
                "maxFileSizeMb": max(1, settings.upload_max_file_size_bytes // 1024 // 1024),
                "allowedExtensions": sorted(allowed_upload_extensions()),
                "defaultParser": "lightweight",
                "ocrEnabled": False,
                "fallbackEnabled": True,
            },
            "retrievalPolicy": {
                "vectorTopK": settings.retrieval_vector_top_k,
                "textTopK": settings.retrieval_text_top_k,
                "finalTopK": settings.retrieval_final_top_k,
                "lowConfidenceThreshold": settings.retrieval_low_confidence_threshold,
            },
            "rateLimitPolicy": {
                "apiKeyDefaultPerMinute": 60,
                "chatPerMinute": 60,
            },
            "storagePolicy": {
                "backend": settings.object_storage_backend,
                "bucket": None,
                "prefix": settings.local_storage_root,
            },
            "retentionPolicy": {
                "apiCallLogDays": 90,
                "auditLogDays": 365,
                "taskRunDays": 180,
                "softDeleteDays": 30,
            },
            "effectiveScopes": SettingsService.effective_scopes(),
        }

    @staticmethod
    def effective_scopes() -> dict[str, str]:
        return {
            "filePolicy": "NEW_TASKS",
            "retrievalPolicy": "NEW_SESSIONS",
            "rateLimitPolicy": "IMMEDIATE",
            "storagePolicy": "NEW_TASKS",
            "retentionPolicy": "MAINTENANCE_WINDOW",
        }

