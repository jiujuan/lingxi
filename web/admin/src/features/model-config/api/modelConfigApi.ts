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

export function testModelProvider(providerId: string) {
  return apiRequest<ConnectionTestResult>(
    `/api/v1/model-providers/${providerId}/connection-tests`,
    { method: 'POST' },
  );
}

export function listModelConfigs(capability?: string) {
  const query = capability ? `?capability=${encodeURIComponent(capability)}` : '';
  return apiRequest<{ data: ModelConfig[] }>(`/api/v1/model-configs${query}`);
}

export function createModelConfig(payload: {
  providerId: string;
  capability: string;
  modelName: string;
  isDefault: boolean;
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
