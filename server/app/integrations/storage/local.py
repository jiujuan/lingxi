from pathlib import Path

from server.app.integrations.storage.base import (
    ObjectMetadata,
    ObjectStorageAdapter,
    StoredObject,
    validate_object_key,
)


class LocalObjectStorage(ObjectStorageAdapter):
    name = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_object(self, object_key: str, data: bytes) -> StoredObject:
        safe_key = validate_object_key(object_key)
        target = self._path_for(safe_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return StoredObject(object_key=safe_key, size=len(data))

    def get_object(self, object_key: str) -> bytes:
        return self._path_for(validate_object_key(object_key)).read_bytes()

    def stat_object(self, object_key: str) -> ObjectMetadata:
        safe_key = validate_object_key(object_key)
        path = self._path_for(safe_key)
        stat = path.stat()
        return ObjectMetadata(object_key=safe_key, size=stat.st_size)

    def delete_object(self, object_key: str) -> None:
        self._path_for(validate_object_key(object_key)).unlink(missing_ok=True)

    def _path_for(self, object_key: str) -> Path:
        target = (self.root / object_key).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError("object_key escapes local storage root")
        return target
