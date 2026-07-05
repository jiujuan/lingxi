import { apiRequest } from '../../../api/client';
import type { SystemSettings } from '../types';

export function getSystemSettings() {
  return apiRequest<SystemSettings>('/api/v1/settings');
}

export function saveSystemSettings(payload: SystemSettings) {
  return apiRequest<SystemSettings>('/api/v1/settings', {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

