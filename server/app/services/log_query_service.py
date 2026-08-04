from datetime import datetime
from math import ceil

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.core.log_redaction import redact_log_payload
from server.app.core.permissions import AccessContext
from server.app.models.model_config import ModelConfig, ModelProvider
from server.app.repositories.api_call_log_repo import ApiCallLogRepository
from server.app.repositories.audit_log_repo import AuditLogRepository
from server.app.repositories.model_call_log_repo import ModelCallLogRepository
from server.app.repositories.task_run_repo import TaskRunRepository


class LogQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_task_runs(self, context: AccessContext, **filters) -> dict:
        items, total = TaskRunRepository(self.session).list_page(
            context.tenant_id, **filters
        )
        return self._with_pagination(
            [self.task_run_to_dict(item) for item in items],
            filters["page"],
            filters["page_size"],
            total,
        )

    def get_task_run(self, context: AccessContext, task_run_id: str) -> dict | None:
        item = TaskRunRepository(self.session).get_for_tenant(
            context.tenant_id, task_run_id
        )
        return self.task_run_to_dict(item) if item else None

    def list_model_calls(self, context: AccessContext, **filters) -> dict:
        items, total = ModelCallLogRepository(self.session).list_page(
            context.tenant_id, **filters
        )
        provider_names = self._provider_names([item.provider_id for item in items])
        model_names = self._model_names([item.model_config_id for item in items])
        return self._with_pagination(
            [
                {
                    "id": item.id,
                    "provider_id": item.provider_id,
                    "provider_name": provider_names.get(item.provider_id),
                    "model_config_id": item.model_config_id,
                    "model_name": model_names.get(item.model_config_id),
                    "run_id": item.run_id,
                    "capability": item.capability,
                    "status": item.status,
                    "latency_ms": item.latency_ms,
                    "token_usage": redact_log_payload(item.token_usage or {}),
                    "batch_id": item.batch_id,
                    "batch_index": item.batch_index,
                    "retry_count": item.retry_count,
                    "split_depth": item.split_depth,
                    "input_char_count": item.input_char_count,
                    "estimated_input_tokens": item.estimated_input_tokens,
                    "output_char_count": item.output_char_count,
                    "estimated_output_tokens": item.estimated_output_tokens,
                    "timeout_phase": item.timeout_phase,
                    "endpoint": redact_log_payload(item.endpoint),
                    "model_name_snapshot": redact_log_payload(
                        item.model_name_snapshot
                    ),
                    "error_code": item.error_code,
                    "error_message": redact_log_payload(item.error_message),
                    "request_id": item.request_id,
                    "created_at": self._iso(item.created_at),
                }
                for item in items
            ],
            filters["page"],
            filters["page_size"],
            total,
        )

    def list_api_calls(self, context: AccessContext, **filters) -> dict:
        items, total = ApiCallLogRepository(self.session).list_page(
            context.tenant_id, **filters
        )
        return self._with_pagination(
            [
                {
                    "id": item.id,
                    "key_prefix": item.key_prefix,
                    "path": item.path,
                    "method": item.method,
                    "status_code": item.status_code,
                    "latency_ms": item.latency_ms,
                    "error_code": item.error_code,
                    "request_id": item.request_id,
                    "request_metadata": redact_log_payload(item.request_metadata or {}),
                    "created_at": self._iso(item.created_at),
                }
                for item in items
            ],
            filters["page"],
            filters["page_size"],
            total,
        )

    def list_audit_logs(self, context: AccessContext, **filters) -> dict:
        items, total = AuditLogRepository(self.session).list_page(
            context.tenant_id, **filters
        )
        return self._with_pagination(
            [
                {
                    "id": item.id,
                    "actor_id": item.actor_id,
                    "action": item.action,
                    "resource_type": item.resource_type,
                    "resource_id": item.resource_id,
                    "before_snapshot": redact_log_payload(item.before_snapshot),
                    "after_snapshot": redact_log_payload(item.after_snapshot),
                    "request_id": item.request_id,
                    "created_at": self._iso(item.created_at),
                }
                for item in items
            ],
            filters["page"],
            filters["page_size"],
            total,
        )

    @staticmethod
    def task_run_to_dict(item) -> dict:
        error = redact_log_payload(item.error or {})
        return {
            "id": item.id,
            "task_type": item.task_type,
            "queue_name": item.queue_name,
            "resource_type": item.resource_type,
            "resource_id": item.resource_id,
            "stage": item.stage,
            "status": item.status,
            "error": error,
            "error_code": error.get("code") if isinstance(error, dict) else None,
            "error_summary": error.get("message") if isinstance(error, dict) else None,
            "retryable": item.status == "FAILED" and item.resource_type == "IMPORT_JOB",
            "request_id": item.request_id,
            "created_at": LogQueryService._iso(item.created_at),
            "updated_at": LogQueryService._iso(item.updated_at),
        }

    def _provider_names(self, provider_ids: list[str | None]) -> dict[str | None, str]:
        ids = [item for item in provider_ids if item]
        if not ids:
            return {}
        rows = self.session.execute(
            select(ModelProvider.id, ModelProvider.name).where(ModelProvider.id.in_(ids))
        ).all()
        return {row.id: row.name for row in rows}

    def _model_names(self, model_config_ids: list[str | None]) -> dict[str | None, str]:
        ids = [item for item in model_config_ids if item]
        if not ids:
            return {}
        rows = self.session.execute(
            select(ModelConfig.id, ModelConfig.model_name).where(ModelConfig.id.in_(ids))
        ).all()
        return {row.id: row.model_name for row in rows}

    @staticmethod
    def _with_pagination(data: list[dict], page: int, page_size: int, total: int) -> dict:
        return {
            "data": data,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total,
                "total_pages": ceil(total / page_size) if total else 0,
            },
        }

    @staticmethod
    def _iso(value: datetime | None) -> str:
        return value.isoformat() if value else ""
