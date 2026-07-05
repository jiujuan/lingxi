import { apiRequest } from '../../../api/client';
import type { ApiCallLog, ApiKey, ApiKeyCreatePayload, ApiKeyCreateResult } from '../types';

export function listApiKeys() {
  return apiRequest<{ data: ApiKey[] }>('/api/v1/api-keys');
}

export function createApiKey(payload: ApiKeyCreatePayload) {
  return apiRequest<ApiKeyCreateResult>('/api/v1/api-keys', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function disableApiKey(keyId: string) {
  return apiRequest<ApiKey>(`/api/v1/api-keys/${keyId}/disable`, { method: 'POST' });
}

export function rotateApiKey(keyId: string) {
  return apiRequest<ApiKeyCreateResult>(`/api/v1/api-keys/${keyId}/rotations`, {
    method: 'POST',
  });
}

export function listApiCallLogs() {
  return apiRequest<{ data: ApiCallLog[] }>('/api/v1/api-call-logs');
}
