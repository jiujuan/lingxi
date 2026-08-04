import { apiRequest } from '../../../api/client';

export type ModelProvider = {
  id: string;
  providerType: string;
  name: string;
  baseUrl: string | null;
  status: string;
  config: Record<string, unknown>;
  secretConfigured: boolean;
};

export type ModelConfig = {
  id: string;
  providerId: string;
  capability: string;
  modelName: string;
  embeddingDimension: number | null;
  maxTokens: number | null;
  timeoutMs: number;
  connectTimeoutMs: number | null;
  writeTimeoutMs: number | null;
  readIdleTimeoutMs: number | null;
  overallTimeoutMs: number | null;
  isDefault: boolean;
  status: string;
  config: Record<string, unknown>;
};

export type ConnectionTestResult = {
  success: boolean;
  status: string;
  latencyMs: number;
  errorCode: string | null;
  errorMessage: string | null;
  providerName: string | null;
  providerType: string | null;
  modelConfigId: string | null;
  modelName: string | null;
  endpoint: string | null;
  timeoutMs: number | null;
  timeoutPhase: string | null;
};

export function listModelProviders() {
  return apiRequest<{ data: ModelProvider[] }>('/api/v1/model-providers');
}

export function createModelProvider(payload: {
  providerType: string;
  name: string;
  baseUrl: string;
  apiKey: string;
  status: string;
}) {
  return apiRequest<ModelProvider>('/api/v1/model-providers', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function testModelProvider(providerId: string, modelConfigId?: string) {
  return apiRequest<ConnectionTestResult>(
    `/api/v1/model-providers/${providerId}/connection-tests`,
    {
      method: 'POST',
      ...(modelConfigId
        ? {
            body: JSON.stringify({ modelConfigId }),
          }
        : {}),
    },
  );
}

export type ModelProviderUpdatePayload = {
  name?: string;
  baseUrl?: string;
  /** Omit to keep the stored secret unchanged. */
  apiKey?: string;
  status?: string;
};

export function updateModelProvider(providerId: string, payload: ModelProviderUpdatePayload) {
  return apiRequest<ModelProvider>(`/api/v1/model-providers/${providerId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function deleteModelProvider(providerId: string) {
  return apiRequest<{ ok: boolean }>(`/api/v1/model-providers/${providerId}`, {
    method: 'DELETE',
  });
}

export function listModelConfigs(capability?: string) {
  const query = capability ? `?capability=${encodeURIComponent(capability)}` : '';
  return apiRequest<{ data: ModelConfig[] }>(`/api/v1/model-configs${query}`);
}

export function createModelConfig(payload: {
  providerId: string;
  capability: string;
  modelName: string;
  maxTokens?: number;
  timeoutMs?: number;
  connectTimeoutMs?: number;
  writeTimeoutMs?: number;
  readIdleTimeoutMs?: number;
  overallTimeoutMs?: number;
  isDefault: boolean;
  config?: Record<string, unknown>;
}) {
  return apiRequest<ModelConfig>('/api/v1/model-configs', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function setDefaultModelConfig(configId: string) {
  return apiRequest<ModelConfig>(`/api/v1/model-configs/${configId}/default`, {
    method: 'PATCH',
  });
}

export type ModelConfigUpdatePayload = {
  modelName?: string;
  embeddingDimension?: number;
  maxTokens?: number;
  timeoutMs?: number;
  connectTimeoutMs?: number;
  writeTimeoutMs?: number;
  readIdleTimeoutMs?: number;
  overallTimeoutMs?: number;
  isDefault?: boolean;
  status?: string;
  config?: Record<string, unknown>;
};

export function updateModelConfig(configId: string, payload: ModelConfigUpdatePayload) {
  return apiRequest<ModelConfig>(`/api/v1/model-configs/${configId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function deleteModelConfig(configId: string) {
  return apiRequest<{ ok: boolean }>(`/api/v1/model-configs/${configId}`, {
    method: 'DELETE',
  });
}
