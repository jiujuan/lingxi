from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.models.api_key import ApiKey


class ApiKeyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, api_key: ApiKey) -> ApiKey:
        self.session.add(api_key)
        self.session.flush()
        return api_key

    def get_for_tenant(self, tenant_id: str, key_id: str) -> ApiKey | None:
        return self.session.scalar(
            select(ApiKey).where(ApiKey.tenant_id == tenant_id, ApiKey.id == key_id)
        )

    def list_for_tenant(self, tenant_id: str) -> list[ApiKey]:
        return list(
            self.session.scalars(
                select(ApiKey)
                .where(ApiKey.tenant_id == tenant_id)
                .order_by(ApiKey.created_at.desc(), ApiKey.id)
            ).all()
        )

    def list_by_prefix(self, key_prefix: str) -> list[ApiKey]:
        return list(
            self.session.scalars(
                select(ApiKey).where(ApiKey.key_prefix == key_prefix)
            ).all()
        )
