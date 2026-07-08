from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import gzip
import json
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.app.integrations.storage.base import ObjectStorageAdapter
from server.app.models.logs import ApiCallLog

logger = logging.getLogger(__name__)

__all__ = ["LogArchiveService", "ArchiveStats"]


@dataclass
class ArchiveStats:
    partitions: int = 0
    rows: int = 0
    bytes: int = 0
    objects: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "partitions": self.partitions,
            "rows": self.rows,
            "bytes": self.bytes,
            "objects": self.objects,
        }


class LogArchiveService:
    """Move old log rows to cold object storage, then purge them from the DB.

    Rows older than the retention window are exported day-by-day as gzipped
    JSONL and uploaded to object storage; only after a partition uploads
    successfully are its rows deleted. That ordering makes the job safe to
    interrupt and idempotent to re-run: a crash before delete just re-uploads
    the same partition next time (overwriting the same key), and a completed
    partition is simply gone from the hot table.
    """

    def __init__(self, session: Session, storage: ObjectStorageAdapter) -> None:
        self.session = session
        self.storage = storage

    def archive_api_call_logs(self, retention_days: int) -> ArchiveStats:
        cutoff = datetime.now(UTC) - timedelta(days=max(1, retention_days))
        stats = ArchiveStats()
        # func.date() yields the calendar day on both SQLite ('YYYY-MM-DD') and
        # PostgreSQL (a date); grouping on it in SQL keeps partitioning off the
        # Python side and out of naive/aware datetime hazards.
        day_column = func.date(ApiCallLog.created_at)
        days = (
            self.session.execute(
                select(day_column)
                .where(ApiCallLog.created_at < cutoff)
                .group_by(day_column)
                .order_by(day_column)
            )
            .scalars()
            .all()
        )
        for day in days:
            day_str = str(day)[:10]
            rows = list(
                self.session.scalars(
                    select(ApiCallLog)
                    .where(
                        func.date(ApiCallLog.created_at) == day,
                        ApiCallLog.created_at < cutoff,
                    )
                    .order_by(ApiCallLog.created_at, ApiCallLog.id)
                ).all()
            )
            if not rows:
                continue
            payload = _gzip_jsonl(_serialize(row) for row in rows)
            object_key = f"archives/api-call-logs/dt={day_str}/api-call-logs.jsonl.gz"
            # Upload first: if this raises, the rows stay put and are retried on
            # the next run rather than being lost.
            self.storage.put_object(object_key, payload)
            for row in rows:
                self.session.delete(row)
            self.session.commit()
            stats.partitions += 1
            stats.rows += len(rows)
            stats.bytes += len(payload)
            stats.objects.append(object_key)
        if stats.rows:
            logger.info(
                "Archived %s api_call_logs rows across %s day(s) to object storage",
                stats.rows,
                stats.partitions,
            )
        return stats


def _serialize(row: ApiCallLog) -> dict:
    return {
        "id": row.id,
        "tenantId": row.tenant_id,
        "apiKeyId": row.api_key_id,
        "keyPrefix": row.key_prefix,
        "path": row.path,
        "method": row.method,
        "statusCode": row.status_code,
        "latencyMs": row.latency_ms,
        "errorCode": row.error_code,
        "requestId": row.request_id,
        "requestMetadata": row.request_metadata or {},
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


def _gzip_jsonl(records) -> bytes:
    body = "\n".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        for record in records
    )
    return gzip.compress(body.encode("utf-8"))
