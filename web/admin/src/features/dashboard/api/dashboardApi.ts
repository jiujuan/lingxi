import { apiRequest } from '../../../api/client';
import type { DashboardSummary } from '../types';

export function getDashboardSummary(days = 7) {
  return apiRequest<DashboardSummary>(`/api/v1/dashboard/summary?days=${days}`);
}

