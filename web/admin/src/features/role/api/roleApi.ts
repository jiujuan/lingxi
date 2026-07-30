import { apiRequest } from '../../../api/client';
import type {
  RoleDetail,
  RoleListFilters,
  RoleListResult,
  RolePayload,
  RolePermission,
} from '../types';

export function listRoles(filters: RoleListFilters) {
  const params = new URLSearchParams({
    page: String(filters.page),
    pageSize: String(filters.pageSize),
  });
  if (filters.keyword) {
    params.set('keyword', filters.keyword);
  }
  return apiRequest<RoleListResult>(`/api/v1/roles?${params.toString()}`);
}

export function getRole(roleId: string) {
  return apiRequest<RoleDetail>(`/api/v1/roles/${roleId}`);
}

export function listAvailablePermissions() {
  return apiRequest<{ data: RolePermission[] }>('/api/v1/roles/available-permissions');
}

export function createRole(payload: RolePayload) {
  return apiRequest<RoleDetail>('/api/v1/roles', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateRole(roleId: string, payload: RolePayload) {
  return apiRequest<RoleDetail>(`/api/v1/roles/${roleId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export function deleteRole(roleId: string) {
  return apiRequest<{ ok: boolean }>(`/api/v1/roles/${roleId}`, {
    method: 'DELETE',
  });
}
