import type { Pagination } from '../knowledge/api/documentApi';

export type TaskRunLog = {
  id: string;
  taskType: string;
  queueName: string;
  resourceType: string;
  resourceId: string;
  stage: string | null;
  status: string;
  error: Record<string, unknown> | null;
  errorCode: string | null;
  errorSummary: string | null;
  retryable: boolean;
  requestId: string | null;
  createdAt: string;
  updatedAt: string;
};

export type ModelCallLog = {
  id: string;
  providerId: string | null;
  providerName: string | null;
  modelConfigId: string | null;
  modelName: string | null;
  runId: string | null;
  capability: string;
  status: string;
  latencyMs: number | null;
  tokenUsage: Record<string, unknown>;
  batchId: string | null;
  batchIndex: string | null;
  retryCount: number;
  splitDepth: number;
  inputCharCount: number | null;
  estimatedInputTokens: number | null;
  outputCharCount: number | null;
  estimatedOutputTokens: number | null;
  timeoutPhase: string | null;
  endpoint: string | null;
  modelNameSnapshot: string | null;
  errorCode: string | null;
  errorMessage: string | null;
  requestId: string | null;
  createdAt: string;
};

export type ApiCallLog = {
  id: string;
  keyPrefix: string | null;
  path: string;
  method: string;
  statusCode: number;
  latencyMs: number;
  errorCode: string | null;
  requestId: string | null;
  requestMetadata: Record<string, unknown>;
  createdAt: string;
};

export type AuditLog = {
  id: string;
  actorId: string | null;
  action: string;
  resourceType: string;
  resourceId: string | null;
  beforeSnapshot: Record<string, unknown> | null;
  afterSnapshot: Record<string, unknown> | null;
  requestId: string | null;
  createdAt: string;
};

export type LogListResponse<T> = {
  data: T[];
  pagination: Pagination;
};

export type LogFilters = {
  requestId: string;
  runId: string;
  batchId: string;
  timeoutPhase: string;
  providerId: string;
  modelConfigId: string;
  taskRunId: string;
  status: string;
  taskType: string;
  page: number;
  pageSize: number;
};
