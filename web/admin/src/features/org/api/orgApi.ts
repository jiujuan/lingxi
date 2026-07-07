import { apiRequest } from '../../../api/client';
import type {
  AdminUser,
  Department,
  DepartmentPayload,
  Role,
  UserCreatePayload,
  UserListFilters,
  UserListResult,
  UserPayload,
} from '../types';

export function listDepartments() {
  return apiRequest<{ data: Department[] }>('/api/v1/departments');
}

export function createDepartment(payload: DepartmentPayload) {
  return apiRequest<Department>('/api/v1/departments', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateDepartment(departmentId: string, payload: DepartmentPayload) {
  return apiRequest<Department>(`/api/v1/departments/${departmentId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export function deleteDepartment(departmentId: string) {
  return apiRequest<{ ok: boolean }>(`/api/v1/departments/${departmentId}`, {
    method: 'DELETE',
  });
}

export function listRoles() {
  return apiRequest<{ data: Role[] }>('/api/v1/roles');
}

export function listUsers(filters: UserListFilters) {
  const params = new URLSearchParams();
  if (filters.keyword) {
    params.set('keyword', filters.keyword);
  }
  if (filters.departmentId) {
    params.set('departmentId', filters.departmentId);
  }
  if (filters.status) {
    params.set('status', filters.status);
  }
  params.set('page', String(filters.page));
  params.set('pageSize', String(filters.pageSize));
  return apiRequest<UserListResult>(`/api/v1/users?${params.toString()}`);
}

export function createUser(payload: UserCreatePayload) {
  return apiRequest<AdminUser>('/api/v1/users', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateUser(userId: string, payload: UserPayload) {
  return apiRequest<AdminUser>(`/api/v1/users/${userId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export function resetUserPassword(userId: string, password: string) {
  return apiRequest<{ ok: boolean }>(`/api/v1/users/${userId}/password`, {
    method: 'POST',
    body: JSON.stringify({ password }),
  });
}

export function disableUser(userId: string) {
  return apiRequest<AdminUser>(`/api/v1/users/${userId}/disable`, { method: 'POST' });
}

export function enableUser(userId: string) {
  return apiRequest<AdminUser>(`/api/v1/users/${userId}/enable`, { method: 'POST' });
}

export function deleteUser(userId: string) {
  return apiRequest<{ ok: boolean }>(`/api/v1/users/${userId}`, { method: 'DELETE' });
}
