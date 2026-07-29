import { apiRequest } from '../../../api/client';
import type {
  CreateKnowledgeCategoryPayload,
  CreateKnowledgeSpacePayload,
  KnowledgeCategory,
  KnowledgeCategoryFilters,
  KnowledgeCategoryStats,
  KnowledgeClassificationStats,
  KnowledgeSpace,
  KnowledgeSpaceStats,
  UpdateKnowledgeCategoryPayload,
  UpdateKnowledgeSpacePayload,
} from '../types/classification';

export function listKnowledgeSpaces() {
  return apiRequest<{ data: KnowledgeSpace[] }>('/api/v1/knowledge-spaces');
}

export function listKnowledgeSpaceStats() {
  return apiRequest<{ data: KnowledgeSpaceStats[]; summary: KnowledgeClassificationStats }>(
    '/api/v1/knowledge-spaces/stats',
  );
}

export function createKnowledgeSpace(payload: CreateKnowledgeSpacePayload) {
  return apiRequest<KnowledgeSpace>('/api/v1/knowledge-spaces', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateKnowledgeSpace(spaceId: string, payload: UpdateKnowledgeSpacePayload) {
  return apiRequest<KnowledgeSpace>(`/api/v1/knowledge-spaces/${encodeURIComponent(spaceId)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export function deleteKnowledgeSpace(spaceId: string) {
  return apiRequest<{ ok: boolean }>(`/api/v1/knowledge-spaces/${encodeURIComponent(spaceId)}`, {
    method: 'DELETE',
  });
}

export function listKnowledgeCategories(filters: KnowledgeCategoryFilters = {}) {
  const query = buildQuery({
    spaceId: filters.spaceId,
    departmentId: filters.departmentId,
  });
  const suffix = query ? `?${query}` : '';
  return apiRequest<{ data: KnowledgeCategory[] }>(`/api/v1/knowledge-categories${suffix}`);
}

export function listKnowledgeCategoryStats(filters: KnowledgeCategoryFilters = {}) {
  const query = buildQuery({
    spaceId: filters.spaceId,
    departmentId: filters.departmentId,
  });
  const suffix = query ? `?${query}` : '';
  return apiRequest<{ data: KnowledgeCategoryStats[]; unclassified: KnowledgeClassificationStats }>(
    `/api/v1/knowledge-categories/stats${suffix}`,
  );
}

export function createKnowledgeCategory(payload: CreateKnowledgeCategoryPayload) {
  return apiRequest<KnowledgeCategory>('/api/v1/knowledge-categories', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateKnowledgeCategory(
  categoryId: string,
  payload: UpdateKnowledgeCategoryPayload,
) {
  return apiRequest<KnowledgeCategory>(
    `/api/v1/knowledge-categories/${encodeURIComponent(categoryId)}`,
    {
      method: 'PUT',
      body: JSON.stringify(payload),
    },
  );
}

export function deleteKnowledgeCategory(categoryId: string) {
  return apiRequest<{ ok: boolean }>(
    `/api/v1/knowledge-categories/${encodeURIComponent(categoryId)}`,
    { method: 'DELETE' },
  );
}

function buildQuery(values: Record<string, string | null | undefined>) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    const trimmed = value?.trim();
    if (trimmed) {
      params.set(key, trimmed);
    }
  });
  return params.toString();
}
