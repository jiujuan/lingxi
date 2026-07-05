from server.app.core.config import settings
from server.app.integrations.storage.base import ObjectStorageAdapter
from server.app.integrations.storage.local import LocalObjectStorage


def get_storage_adapter() -> ObjectStorageAdapter:
    if settings.object_storage_backend == "local":
        return LocalObjectStorage(settings.local_storage_root)
    raise ValueError(f"Unsupported object storage backend: {settings.object_storage_backend}")
