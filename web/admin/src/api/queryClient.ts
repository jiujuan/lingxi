import { QueryClient } from '@tanstack/react-query';

import { ApiError } from './client';

/**
 * Shared React Query client.
 *
 * - 4xx (including 401/403) are never retried — they are deterministic; the 401
 *   redirect is already handled inside apiRequest.
 * - Transient errors (5xx / network) get one retry.
 * - Cached data is considered fresh for 30s, so switching pages does not refetch
 *   everything on every navigation.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
          return false;
        }
        return failureCount < 1;
      },
    },
    mutations: {
      retry: false,
    },
  },
});

/** Stable query-key factory so invalidation stays consistent across features. */
export const queryKeys = {
  dashboard: (days: number) => ['dashboard', days] as const,
  settings: () => ['settings'] as const,
  apiKeys: () => ['api-keys'] as const,
  apiCallLogs: () => ['api-call-logs'] as const,
  departments: () => ['departments'] as const,
  users: (filters: unknown) => ['users', filters] as const,
  roles: () => ['roles'] as const,
  roleOptions: () => ['role-options'] as const,
  modelProviders: () => ['model-providers'] as const,
  modelConfigs: () => ['model-configs'] as const,
  taskRunLogs: (filters: unknown) => ['logs', 'tasks', filters] as const,
  modelCallLogs: (filters: unknown) => ['logs', 'models', filters] as const,
  apiLogs: (filters: unknown) => ['logs', 'api', filters] as const,
  auditLogs: (filters: unknown) => ['logs', 'audit', filters] as const,
};
