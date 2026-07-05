from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext
from server.app.repositories.dashboard_repo import DashboardRepository


class DashboardService:
    def __init__(self, session: Session) -> None:
        self.repo = DashboardRepository(session)

    def summary(self, context: AccessContext, days: int) -> dict:
        since = self._since(days)
        task_counts = self.repo.task_status_counts(context.tenant_id, since)
        import_counts = self.repo.import_job_status_counts(context.tenant_id, since)
        visible_task_counts = task_counts if sum(task_counts.values()) else import_counts
        task_total = sum(visible_task_counts.values())
        task_success = visible_task_counts.get("SUCCESS", 0) + visible_task_counts.get(
            "COMPLETED", 0
        )
        task_failed = visible_task_counts.get("FAILED", 0)

        return {
            "metrics": {
                "document_count": self.repo.document_count(context.tenant_id),
                "qa_pair_count": self.repo.qa_pair_count(context.tenant_id),
                "task_success_rate": self._rate(task_success, task_total),
                "task_failure_rate": self._rate(task_failed, task_total),
                "api_call_count": self.repo.api_call_count(context.tenant_id, since),
            },
            "ingestion_health": self.ingestion_health(context, days, import_counts),
            "qa_health": self.qa_health(context, days),
            "recent_tasks": self._recent_tasks(context),
            "risk_events": self.repo.risk_events(context.tenant_id),
        }

    def ingestion_health(
        self, context: AccessContext, days: int, counts: dict | None = None
    ) -> dict:
        since = self._since(days)
        counts = counts or self.repo.import_job_status_counts(context.tenant_id, since)
        total = sum(counts.values())
        success = counts.get("COMPLETED", 0)
        failed = counts.get("FAILED", 0)
        return {
            "success_rate": self._rate(success, total),
            "failure_rate": self._rate(failed, total),
            "stages": self.repo.stage_status_counts(context.tenant_id, since),
            "trend": [],
        }

    def qa_health(self, context: AccessContext, days: int) -> dict:
        return self.repo.query_run_stats(context.tenant_id, self._since(days))

    def recent_activity(self, context: AccessContext) -> dict:
        return {
            "recentTasks": self._recent_tasks(context),
            "riskEvents": self.repo.risk_events(context.tenant_id),
        }

    def _recent_tasks(self, context: AccessContext) -> list[dict]:
        task_runs = self.repo.recent_tasks(context.tenant_id)
        if task_runs:
            return [
                {
                    "id": item.id,
                    "taskType": item.task_type,
                    "status": item.status,
                    "stage": item.stage,
                    "requestId": item.request_id,
                    "createdAt": item.created_at.isoformat() if item.created_at else "",
                }
                for item in task_runs
            ]
        return [
            {
                "id": item.id,
                "taskType": "import_job",
                "status": item.status,
                "stage": item.stage,
                "requestId": None,
                "createdAt": item.created_at.isoformat() if item.created_at else "",
            }
            for item in self.repo.recent_import_jobs(context.tenant_id)
        ]

    @staticmethod
    def _since(days: int) -> datetime | None:
        if days <= 0:
            return None
        return datetime.now(UTC) - timedelta(days=days)

    @staticmethod
    def _rate(count: int, total: int) -> float:
        return round(count * 100 / total, 2) if total else 0
