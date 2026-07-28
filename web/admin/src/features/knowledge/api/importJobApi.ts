import { ApiError, apiRequest } from '../../../api/client';
import type { Schemas } from '../../../api/schema-helpers';
import { getToken, redirectToLogin } from '../../../auth/authStore';
import type { ImportClassificationPayload } from '../types/classification';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

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

export type PermissionPayload = Schemas['ImportPermissionRequest'];

export type CreateImportJobPayload = Omit<Schemas['ImportJobCreateRequest'], 'classification'> & {
  classification?: ImportClassificationPayload | null;
};

export function createImportJob(payload: CreateImportJobPayload) {
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
  return apiRequest<ImportJob>(`/api/v1/import-jobs/${encodeURIComponent(jobId)}/files`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Upload a file as multipart/form-data with progress reporting.
 *
 * Uses XMLHttpRequest because fetch does not expose upload progress. Sends the
 * raw file (no base64 bloat) plus the client-computed SHA-256 checksum.
 */
export function uploadImportJobFile(
  jobId: string,
  file: File,
  options: { objectKey: string; checksum: string; onProgress?: (percent: number) => void },
): Promise<ImportJob> {
  return new Promise<ImportJob>((resolve, reject) => {
    const form = new FormData();
    form.append('file', file, file.name);
    form.append('object_key', options.objectKey);
    form.append('checksum', options.checksum);

    const token = getToken();
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE_URL}/api/v1/import-jobs/${encodeURIComponent(jobId)}/file`);
    if (token) {
      xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    }
    // Do NOT set Content-Type: the browser adds the multipart boundary.

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && options.onProgress) {
        options.onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as ImportJob);
        } catch {
          reject(new ApiError(xhr.status, 'PARSE_ERROR', '上传响应解析失败'));
        }
        return;
      }
      if (xhr.status === 401 && token) {
        redirectToLogin();
      }
      reject(xhrError(xhr));
    };
    xhr.onerror = () => reject(new ApiError(0, 'NETWORK_ERROR', '网络异常，请检查连接后重试'));
    xhr.send(form);
  });
}

function xhrError(xhr: XMLHttpRequest): ApiError {
  const fallback = `上传失败（HTTP ${xhr.status}）`;
  try {
    const payload = JSON.parse(xhr.responseText) as Record<string, unknown>;
    const err = payload.error as Record<string, unknown> | undefined;
    if (err && typeof err === 'object') {
      return new ApiError(
        xhr.status,
        String(err.code ?? 'REQUEST_ERROR'),
        String(err.message ?? fallback),
        (payload.requestId as string | undefined) ?? undefined,
      );
    }
  } catch {
    // non-JSON body
  }
  return new ApiError(xhr.status, 'REQUEST_ERROR', fallback);
}

export function getImportJob(jobId: string) {
  return apiRequest<ImportJob>(`/api/v1/import-jobs/${encodeURIComponent(jobId)}`);
}

export function retryImportJob(jobId: string) {
  return apiRequest<ImportJob>(`/api/v1/import-jobs/${encodeURIComponent(jobId)}/retries`, {
    method: 'POST',
  });
}

export function regenerateQaPairs(documentId: string) {
  return apiRequest<ImportJob>(
    `/api/v1/documents/${encodeURIComponent(documentId)}/qa-regenerations`,
    {
      method: 'POST',
    },
  );
}

export function listQaPairs(documentId: string) {
  return apiRequest<{ data: QaPair[] }>(
    `/api/v1/documents/${encodeURIComponent(documentId)}/qa-pairs?page=1&pageSize=20`,
  );
}
