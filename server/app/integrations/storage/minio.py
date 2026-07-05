from server.app.integrations.storage.base import ObjectStorageAdapter


class MinioObjectStorage(ObjectStorageAdapter):
    name = "minio"

    def __init__(self, *_args, **_kwargs) -> None:
        raise NotImplementedError("MinIO storage is reserved for a later deployment task")
