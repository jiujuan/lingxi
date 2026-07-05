import { apiRequest } from '../../../api/client';
import type {
  ApiCallLog,
  AuditLog,
  LogFilters,
  LogListResponse,
  ModelCallLog,
  TaskRunLog,
} from '../types';

export function listTaskRunLogs(filters: LogFilters) {
  return apiRequest<LogListResponse<TaskRunLog>>(`/api/v1/logs/task-runs?${buildParams({
    requestId: filters.requestId,
    taskRunId: filters.taskRunId,
    status: filters.status,
    taskType: filters.taskType,
    page: String(filters.page),
    pageSize: String(filters.pageSize),
  })}`);
}

export function listModelCallLogs(filters: LogFilters) {
  return apiRequest<LogListResponse<ModelCallLog>>(`/api/v1/logs/model-calls?${buildParams({
    requestId: filters.requestId,
    runId: filters.runId,
    status: filters.status,
    page: String(filters.page),
    pageSize: String(filters.pageSize),
  })}`);
}

export function listApiCallLogs(filters: LogFilters) {
  return apiRequest<LogListResponse<ApiCallLog>>(`/api/v1/logs/api-calls?${buildParams({
    requestId: filters.requestId,
    statusCode: filters.status,
    page: String(filters.page),
    pageSize: String(filters.pageSize),
  })}`);
}

export function listAuditLogs(filters: LogFilters) {
  return apiRequest<LogListResponse<AuditLog>>(`/api/v1/logs/audit?${buildParams({
    requestId: filters.requestId,
    action: filters.taskType,
    page: String(filters.page),
    pageSize: String(filters.pageSize),
  })}`);
}

export function retryTaskRun(taskRunId: string) {
  return apiRequest<{ id: string; resourceId: string; status: string; stage: string; retryCount: number }>(
    `/api/v1/task-runs/${taskRunId}/retry`,
    { method: 'POST' },
  );
}

function buildParams(values: Record<string, string>) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value.trim()) {
      params.set(key, value.trim());
    }
  });
  return params.toString();
}

