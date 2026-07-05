import { apiRequest } from '../../../api/client';
import type { PermissionPayload } from './importJobApi';

export type Pagination = {
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
};

export type NamedSubject = {
  id: string;
  name: string;
};

export type DocumentPermission = {
  allAuthenticated: boolean;
  departments: NamedSubject[];
  roles: NamedSubject[];
  users: NamedSubject[];
};

export type DocumentJobSummary = {
  id: string;
  status: string;
  stage: string;
  progress: number;
  retryCount: number;
  errorCode: string | null;
  errorMessage: string | null;
  failedStage: string | null;
  retryable: boolean;
};

export type ProcessingLog = {
  id: string;
  taskType: string;
  queueName: string;
  stage: string | null;
  status: string;
  error: Record<string, unknown> | null;
  requestId: string | null;
};

export type KnowledgeDocument = {
  id: string;
  title: string;
  fileName: string;
  fileType: string;
  mimeType: string;
  fileSize: number;
  status: string;
  parserName: string | null;
  pageCount: number | null;
  qaPairCount: number;
  chunkCount: number;
  permissions: DocumentPermission;
  latestJob: DocumentJobSummary | null;
  lastErrorCode: string | null;
  lastErrorMessage: string | null;
  createdAt: string;
  updatedAt: string;
};

export type KnowledgeDocumentDetail = KnowledgeDocument & {
  parserVersion: string | null;
  objectKey: string;
  checksum: string;
  processingLogs: ProcessingLog[];
};

export type DocumentChunk = {
  id: string;
  documentId: string;
  chunkIndex: number;
  titlePath: string[];
  content: string;
  pageNo: number | null;
  tokenCount: number;
  sourceLocator: Record<string, unknown>;
  status: string;
};

export type DocumentFilters = {
  keyword: string;
  fileType: string;
  status: string;
  departmentId: string;
  roleId: string;
  page: number;
  pageSize: number;
};

export function listDocuments(filters: DocumentFilters) {
  const params = buildParams({
    keyword: filters.keyword,
    fileType: filters.fileType,
    status: filters.status,
    departmentId: filters.departmentId,
    roleId: filters.roleId,
    page: String(filters.page),
    pageSize: String(filters.pageSize),
  });
  return apiRequest<{ data: KnowledgeDocument[]; pagination: Pagination }>(
    `/api/v1/documents?${params}`,
  );
}

export function getDocument(documentId: string) {
  return apiRequest<KnowledgeDocumentDetail>(`/api/v1/documents/${documentId}`);
}

export function listDocumentChunks(documentId: string) {
  return apiRequest<{ data: DocumentChunk[]; pagination: Pagination }>(
    `/api/v1/documents/${documentId}/chunks?page=1&pageSize=20`,
  );
}

export function updateDocumentPermissions(documentId: string, payload: PermissionPayload) {
  return apiRequest<DocumentPermission>(`/api/v1/documents/${documentId}/permissions`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function deleteDocument(documentId: string) {
  return apiRequest<{ id: string; status: string }>(`/api/v1/documents/${documentId}`, {
    method: 'DELETE',
  });
}

function buildParams(values: Record<string, string>) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value.trim()) {
      params.set(key, value.trim());
    }
  });
  return params.toString();
}
