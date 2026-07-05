import { apiRequest } from '../../../api/client';

export type ImportJob = {
  id: string;
  documentId: string | null;
  status: string;
  stage: string;
  progress: number;
  retryCount: number;
  errorCode: string | null;
  errorMessage: string | null;
  failedStage: string | null;
  retryable: boolean;
  file: {
    id: string;
    objectKey: string;
    fileName: string;
    mimeType: string;
    fileSize: number;
    checksum: string;
  } | null;
};

export type QaPair = {
  id: string;
  documentId: string;
  chunkId: string | null;
  question: string;
  answer: string;
  quote: string | null;
  pageNo: number | null;
  embeddingStatus: string;
  status: string;
};

export type PermissionPayload = {
  departmentIds?: string[];
  roleIds?: string[];
  userIds?: string[];
  allAuthenticated: boolean;
};

export function createImportJob(payload: {
  title: string;
  permission: PermissionPayload;
  parseOptions: Record<string, unknown>;
  processingOptions: Record<string, unknown>;
}) {
  return apiRequest<ImportJob>('/api/v1/import-jobs', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function bindImportJobFile(
  jobId: string,
  payload: {
    objectKey: string;
    fileName: string;
    mimeType: string;
    fileSize: number;
    checksum: string;
    contentBase64: string;
  },
) {
  return apiRequest<ImportJob>(`/api/v1/import-jobs/${jobId}/files`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getImportJob(jobId: string) {
  return apiRequest<ImportJob>(`/api/v1/import-jobs/${jobId}`);
}

export function retryImportJob(jobId: string) {
  return apiRequest<ImportJob>(`/api/v1/import-jobs/${jobId}/retries`, {
    method: 'POST',
  });
}

export function regenerateQaPairs(documentId: string) {
  return apiRequest<ImportJob>(`/api/v1/documents/${documentId}/qa-regenerations`, {
    method: 'POST',
  });
}

export function listQaPairs(documentId: string) {
  return apiRequest<{ data: QaPair[] }>(
    `/api/v1/documents/${documentId}/qa-pairs?page=1&pageSize=20`,
  );
}
