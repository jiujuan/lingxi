from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from server.app.models.chat import QueryCitation, QueryRun
from server.app.models.document import Document
from server.app.models.import_job import ImportJob
from server.app.models.logs import ApiCallLog, AuditLog, TaskRun
from server.app.models.model_config import ModelCallLog
from server.app.models.qa_pair import QaPair


class DashboardRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def document_count(self, tenant_id: str) -> int:
        return self.session.scalar(
            select(func.count()).select_from(Document).where(
                Document.tenant_id == tenant_id,
                Document.deleted_at.is_(None),
            )
        ) or 0

    def qa_pair_count(self, tenant_id: str) -> int:
        return self.session.scalar(
            select(func.count()).select_from(QaPair).where(
                QaPair.tenant_id == tenant_id,
                QaPair.deleted_at.is_(None),
            )
        ) or 0

    def api_call_count(self, tenant_id: str, since: datetime | None) -> int:
        # Count external API usage only. The api_call_logs table now also holds
        # admin-console (/api/*) traffic for troubleshooting, but this dashboard
        # metric means "external API calls served", so it stays scoped to the
        # OpenAI-compatible gateway (/v1/*).
        query = select(func.count()).select_from(ApiCallLog).where(
            ApiCallLog.tenant_id == tenant_id,
            ApiCallLog.path.like("/v1/%"),
        )
        if since:
            query = query.where(ApiCallLog.created_at >= since)
        return self.session.scalar(query) or 0

    def import_job_status_counts(self, tenant_id: str, since: datetime | None) -> dict:
        query = select(ImportJob.status, func.count()).where(ImportJob.tenant_id == tenant_id)
        if since:
            query = query.where(ImportJob.created_at >= since)
        rows = self.session.execute(query.group_by(ImportJob.status)).all()
        return {row.status: row[1] for row in rows}

    def task_status_counts(self, tenant_id: str, since: datetime | None) -> dict:
        query = select(TaskRun.status, func.count()).where(
            TaskRun.tenant_id == tenant_id,
            TaskRun.deleted_at.is_(None),
        )
        if since:
            query = query.where(TaskRun.created_at >= since)
        rows = self.session.execute(query.group_by(TaskRun.status)).all()
        return {row.status: row[1] for row in rows}

    def stage_status_counts(self, tenant_id: str, since: datetime | None) -> list[dict]:
        query = (
            select(
                ImportJob.stage,
                func.sum(case((ImportJob.status == "COMPLETED", 1), else_=0)),
                func.sum(case((ImportJob.status == "FAILED", 1), else_=0)),
                func.count(),
            )
            .where(ImportJob.tenant_id == tenant_id)
            .group_by(ImportJob.stage)
        )
        if since:
            query = query.where(ImportJob.created_at >= since)
        return [
            {
                "stage": row[0],
                "successCount": int(row[1] or 0),
                "failureCount": int(row[2] or 0),
                "totalCount": int(row[3] or 0),
            }
            for row in self.session.execute(query).all()
        ]

    def query_run_stats(self, tenant_id: str, since: datetime | None) -> dict:
        query = select(QueryRun).where(QueryRun.tenant_id == tenant_id)
        if since:
            query = query.where(QueryRun.created_at >= since)
        rows = list(self.session.scalars(query).all())
        if not rows:
            return {
                "queryCount": 0,
                "citationCoverageRate": 0,
                "refusalRate": 0,
                "hitRate": 0,
                "firstTokenLatencyMs": 0,
            }

        run_db_ids = [item.id for item in rows]
        cited_run_ids = set(
            self.session.scalars(
                select(QueryCitation.run_id).where(QueryCitation.run_id.in_(run_db_ids))
            ).all()
        )
        refused = [
            item
            for item in rows
            if (item.retrieval_snapshot or {}).get("hasAnswer") is False
            or item.status in {"REFUSED", "NO_ANSWER"}
        ]
        success = [item for item in rows if item.status in {"COMPLETED", "SUCCESS"}]
        latencies = [
            int((item.retrieval_snapshot or {}).get("firstTokenLatencyMs") or item.latency_ms or 0)
            for item in rows
            if ((item.retrieval_snapshot or {}).get("firstTokenLatencyMs") or item.latency_ms)
        ]
        total = len(rows)
        return {
            "queryCount": total,
            "citationCoverageRate": round(len(cited_run_ids) * 100 / total, 2),
            "refusalRate": round(len(refused) * 100 / total, 2),
            "hitRate": round(len(success) * 100 / total, 2),
            "firstTokenLatencyMs": int(sum(latencies) / len(latencies)) if latencies else 0,
        }

    def recent_tasks(self, tenant_id: str, limit: int = 8) -> list[TaskRun]:
        return list(
            self.session.scalars(
                select(TaskRun)
                .where(TaskRun.tenant_id == tenant_id, TaskRun.deleted_at.is_(None))
                .order_by(TaskRun.created_at.desc(), TaskRun.id.desc())
                .limit(limit)
            ).all()
        )

    def recent_import_jobs(self, tenant_id: str, limit: int = 8) -> list[ImportJob]:
        return list(
            self.session.scalars(
                select(ImportJob)
                .where(ImportJob.tenant_id == tenant_id, ImportJob.deleted_at.is_(None))
                .order_by(ImportJob.created_at.desc(), ImportJob.id.desc())
                .limit(limit)
            ).all()
        )

    def risk_events(self, tenant_id: str, limit: int = 8) -> list[dict]:
        task_rows = self.session.scalars(
            select(TaskRun)
            .where(
                TaskRun.tenant_id == tenant_id,
                TaskRun.status == "FAILED",
                TaskRun.deleted_at.is_(None),
            )
            .order_by(TaskRun.created_at.desc(), TaskRun.id.desc())
            .limit(limit)
        ).all()
        import_rows = self.session.scalars(
            select(ImportJob)
            .where(
                ImportJob.tenant_id == tenant_id,
                ImportJob.status == "FAILED",
                ImportJob.deleted_at.is_(None),
            )
            .order_by(ImportJob.created_at.desc(), ImportJob.id.desc())
            .limit(limit)
        ).all()
        model_rows = self.session.scalars(
            select(ModelCallLog)
            .where(ModelCallLog.tenant_id == tenant_id, ModelCallLog.status == "FAILED")
            .order_by(ModelCallLog.created_at.desc(), ModelCallLog.id.desc())
            .limit(limit)
        ).all()
        audit_rows = self.session.scalars(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id, AuditLog.deleted_at.is_(None))
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
        ).all()
        events = [
            {
                "type": "TASK_FAILED",
                "severity": "HIGH",
                "message": item.task_type,
                "requestId": item.request_id,
                "createdAt": item.created_at.isoformat() if item.created_at else "",
            }
            for item in task_rows
        ]
        events.extend(
            {
                "type": "IMPORT_JOB_FAILED",
                "severity": "HIGH",
                "message": item.error_code or item.stage,
                "requestId": None,
                "createdAt": item.created_at.isoformat() if item.created_at else "",
            }
            for item in import_rows
        )
        events.extend(
            {
                "type": "MODEL_CALL_FAILED",
                "severity": "HIGH",
                "message": item.error_code or item.capability,
                "requestId": item.request_id,
                "createdAt": item.created_at.isoformat() if item.created_at else "",
            }
            for item in model_rows
        )
        events.extend(
            {
                "type": "AUDIT",
                "severity": "MEDIUM",
                "message": item.action,
                "requestId": item.request_id,
                "createdAt": item.created_at.isoformat() if item.created_at else "",
            }
            for item in audit_rows
        )
        return sorted(events, key=lambda item: item["createdAt"], reverse=True)[:limit]
