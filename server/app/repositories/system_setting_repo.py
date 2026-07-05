from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.models.logs import SystemSetting


class SystemSettingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: str, key: str) -> SystemSetting | None:
        return self.session.scalar(
            select(SystemSetting).where(
                SystemSetting.tenant_id == tenant_id,
                SystemSetting.key == key,
                SystemSetting.deleted_at.is_(None),
            )
        )

    def upsert(self, tenant_id: str, key: str, value: dict) -> SystemSetting:
        setting = self.get(tenant_id, key)
        if setting is None:
            setting = SystemSetting(tenant_id=tenant_id, key=key, value=value)
            self.session.add(setting)
        else:
            setting.value = value
        self.session.flush()
        return setting

