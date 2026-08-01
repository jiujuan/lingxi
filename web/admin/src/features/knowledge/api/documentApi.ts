import { apiRequest } from '../../../api/client';
import type { Schemas } from '../../../api/schema-helpers';
import type {
  KnowledgeClassificationPath,
  UpdateDocumentClassificationPayload,
} from '../types/classification';
import type { PermissionPayload } from './importJobApi';

export type Pagination = Schemas['PaginationResponse'];
export type DocumentProcessingSummary = Schemas['DocumentProcessingSummaryResponse'];

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

export type KnowledgeDocument = Omit<Schemas['DocumentListItemResponse'], 'classification'> & {
  classification?: KnowledgeClassificationPath | null;
};

export type KnowledgeDocumentDetail = Omit<Schemas['DocumentDetailResponse'], 'classification'> & {
  classification?: KnowledgeClassificationPath | null;
};

export type BulkUpdateDocumentClassificationPayload =
  Schemas['BulkUpdateDocumentClassificationRequest'];

export type BulkUpdateDocumentClassificationResult = Omit<
  Schemas['BulkUpdateDocumentClassificationResponse'],
  'classification'
> & {
  classification?: KnowledgeClassificationPath | null;
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
  /** Knowledge space filter (classification), distinct from permission scope. */
  spaceId: string;
  /** Classification department filter, distinct from permission departmentId below. */
  classificationDepartmentId: string;
  categoryId: string;
  isUnclassified: boolean;
  departmentId: string;
  roleId: string;
  page: number;
  pageSize: number;
};

export async function listDocuments(filters: DocumentFilters) {
  const params = buildParams({
    keyword: filters.keyword,
    fileType: filters.fileType,
    status: filters.status,
    spaceId: filters.spaceId,
    classificationDepartmentId: filters.classificationDepartmentId,
    categoryId: filters.categoryId,
    isUnclassified: filters.isUnclassified ? 'true' : '',
    departmentId: filters.departmentId,
    roleId: filters.roleId,
    page: String(filters.page),
    pageSize: String(filters.pageSize),
  });
  const result = await apiRequest<{
    data: RawKnowledgeDocument[];
    pagination: Pagination;
  }>(`/api/v1/documents?${params}`);
  return {
    ...result,
    data: result.data.map(mapKnowledgeDocument),
  };
}

export function getDocumentProcessingSummary() {
  return apiRequest<DocumentProcessingSummary>('/api/v1/documents/summary');
}

export async function getDocument(documentId: string) {
  const result = await apiRequest<RawKnowledgeDocumentDetail>(
    `/api/v1/documents/${encodeURIComponent(documentId)}`,
  );
  return mapKnowledgeDocumentDetail(result);
}

export function listDocumentChunks(documentId: string) {
  return apiRequest<{ data: DocumentChunk[]; pagination: Pagination }>(
    `/api/v1/documents/${encodeURIComponent(documentId)}/chunks?page=1&pageSize=20`,
  );
}

export function updateDocumentPermissions(documentId: string, payload: PermissionPayload) {
  return apiRequest<DocumentPermission>(
    `/api/v1/documents/${encodeURIComponent(documentId)}/permissions`,
    {
      method: 'PATCH',
      body: JSON.stringify(payload),
    },
  );
}

export async function updateDocumentClassification(
  documentId: string,
  payload: UpdateDocumentClassificationPayload,
) {
  const result = await apiRequest<Schemas['DocumentClassificationResponse']>(
    `/api/v1/documents/${encodeURIComponent(documentId)}/classification`,
    {
      method: 'PATCH',
      body: JSON.stringify(payload),
    },
  );
  return mapClassification(result);
}

export async function bulkUpdateDocumentClassification(
  payload: BulkUpdateDocumentClassificationPayload,
): Promise<BulkUpdateDocumentClassificationResult> {
  const result = await apiRequest<Schemas['BulkUpdateDocumentClassificationResponse']>(
    '/api/v1/documents/bulk-classification',
    {
      method: 'PATCH',
      body: JSON.stringify(payload),
    },
  );
  return {
    ...result,
    classification: mapClassification(result.classification),
  };
}

export function deleteDocument(documentId: string) {
  return apiRequest<{ id: string; status: string }>(
    `/api/v1/documents/${encodeURIComponent(documentId)}`,
    {
      method: 'DELETE',
    },
  );
}

type RawKnowledgeDocument = Omit<Schemas['DocumentListItemResponse'], 'classification'> & {
  classification?: Schemas['DocumentClassificationResponse'] | null;
};

type RawKnowledgeDocumentDetail = Omit<Schemas['DocumentDetailResponse'], 'classification'> & {
  classification?: Schemas['DocumentClassificationResponse'] | null;
};

function mapKnowledgeDocument(document: RawKnowledgeDocument): KnowledgeDocument {
  return {
    ...document,
    classification: mapClassification(document.classification),
  };
}

function mapKnowledgeDocumentDetail(document: RawKnowledgeDocumentDetail): KnowledgeDocumentDetail {
  return {
    ...document,
    classification: mapClassification(document.classification),
  };
}

function mapClassification(
  classification: Schemas['DocumentClassificationResponse'] | null | undefined,
): KnowledgeClassificationPath | null {
  if (!classification) {
    return null;
  }
  const departmentId = classification.categoryDepartmentId;
  const departmentName = classification.categoryDepartment?.name ?? null;
  return {
    spaceId: classification.knowledgeSpaceId,
    spaceName: classification.knowledgeSpace?.name ?? null,
    departmentId,
    departmentName,
    classificationDepartmentId: departmentId,
    classificationDepartmentName: departmentName,
    categoryId: classification.knowledgeCategoryId,
    categoryName: classification.knowledgeCategory?.name ?? null,
  };
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
