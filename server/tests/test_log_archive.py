import gzip
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from server.tests.test_auth_rbac import build_test_client


class _FakeStorage:
    """Minimal ObjectStorageAdapter capturing uploads in memory."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, object_key: str, data: bytes):
        self.objects[object_key] = data
        return None

    def get_object(self, object_key: str) -> bytes:
        return self.objects[object_key]


def test_archive_api_call_logs_uploads_old_rows_then_purges_them():
    from server.app.models.logs import ApiCallLog
    from server.app.services.log_archive_service import LogArchiveService

    _, SessionLocal = build_test_client()

    old_day_a = datetime.now(UTC) - timedelta(days=200)
    old_day_b = datetime.now(UTC) - timedelta(days=201)
    recent = datetime.now(UTC) - timedelta(days=1)

    with SessionLocal() as session:
        session.add_all(
            [
                ApiCallLog(
                    tenant_id="t1",
                    key_prefix="lk_live_a",
                    path="/v1/chat/completions",
                    method="POST",
                    status_code=200,
                    latency_ms=5,
                    request_metadata={"model": "x"},
                    created_at=old_day_a,
                ),
                ApiCallLog(
                    tenant_id="t1",
                    path="/api/v1/knowledge",
                    method="GET",
                    status_code=200,
                    latency_ms=3,
                    created_at=old_day_b,
                ),
                ApiCallLog(
                    tenant_id="t1",
                    path="/api/v1/logs/api-calls",
                    method="GET",
                    status_code=200,
                    latency_ms=2,
                    created_at=recent,
                ),
            ]
        )
        session.commit()

    storage = _FakeStorage()
    with SessionLocal() as session:
        stats = LogArchiveService(session, storage).archive_api_call_logs(90)

    # Two old rows on two distinct days -> two partitions archived.
    assert stats.rows == 2
    assert stats.partitions == 2
    assert stats.bytes > 0
    assert len(storage.objects) == 2
    assert all(key.startswith("archives/api-call-logs/dt=") for key in storage.objects)

    # Only the within-retention row survives in the hot table.
    with SessionLocal() as session:
        remaining = session.scalars(select(ApiCallLog)).all()
    assert len(remaining) == 1
    assert remaining[0].path == "/api/v1/logs/api-calls"

    # The archived object is gzipped JSONL that round-trips to the source rows.
    archived_paths = set()
    for data in storage.objects.values():
        for line in gzip.decompress(data).decode("utf-8").splitlines():
            record = json.loads(line)
            archived_paths.add(record["path"])
            assert "createdAt" in record
    assert archived_paths == {"/v1/chat/completions", "/api/v1/knowledge"}


def test_archive_api_call_logs_is_noop_when_nothing_is_old():
    from server.app.models.logs import ApiCallLog
    from server.app.services.log_archive_service import LogArchiveService

    _, SessionLocal = build_test_client()
    with SessionLocal() as session:
        session.add(
            ApiCallLog(
                tenant_id="t1",
                path="/api/v1/knowledge",
                method="GET",
                status_code=200,
                latency_ms=3,
                created_at=datetime.now(UTC) - timedelta(days=2),
            )
        )
        session.commit()

    storage = _FakeStorage()
    with SessionLocal() as session:
        stats = LogArchiveService(session, storage).archive_api_call_logs(90)

    assert stats.rows == 0
    assert stats.partitions == 0
    assert storage.objects == {}
    with SessionLocal() as session:
        assert session.scalars(select(ApiCallLog)).all()  # row untouched
