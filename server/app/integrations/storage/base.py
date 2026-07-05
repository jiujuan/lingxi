from dataclasses import dataclass
import re


@dataclass(frozen=True)
class StoredObject:
    object_key: str
    size: int
    checksum: str | None = None


@dataclass(frozen=True)
class ObjectMetadata:
    object_key: str
    size: int


class ObjectStorageAdapter:
    name = "base"

    def put_object(self, object_key: str, data: bytes) -> StoredObject:
        raise NotImplementedError

    def get_object(self, object_key: str) -> bytes:
        raise NotImplementedError

    def stat_object(self, object_key: str) -> ObjectMetadata:
        raise NotImplementedError

    def delete_object(self, object_key: str) -> None:
        raise NotImplementedError


def validate_object_key(object_key: str) -> str:
    key = object_key.strip()
    if not key:
        raise ValueError("object_key is empty")
    if "\\" in key:
        raise ValueError("object_key must use forward slashes")
    if key.startswith("/"):
        raise ValueError("object_key cannot be absolute")
    if re.match(r"^[A-Za-z]:", key):
        raise ValueError("object_key cannot contain a drive letter")

    parts = key.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("object_key contains an unsafe path segment")
    return key
