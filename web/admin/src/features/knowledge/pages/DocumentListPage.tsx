import { useEffect, useState } from 'react';

import { errorMessage } from '../../../api/client';
import {
  deleteDocument,
  getDocument,
  listDocumentChunks,
  listDocuments,
  type DocumentChunk,
  type DocumentFilters,
  type KnowledgeDocument,
  type KnowledgeDocumentDetail,
  type Pagination,
} from '../api/documentApi';
import { listKnowledgeCategoryStats, listKnowledgeSpaceStats } from '../api/classificationApi';
import { getImportJob, retryImportJob, type ImportJob } from '../api/importJobApi';
import { BulkDocumentClassificationModal } from '../components/BulkDocumentClassificationModal';
import { DocumentClassificationModal } from '../components/DocumentClassificationModal';
import { DocumentDetailPanel } from '../components/DocumentDetailPanel';
import { DocumentList } from '../components/DocumentList';
import { DocumentPermissionModal } from '../components/DocumentPermissionModal';

const DEFAULT_FILTERS: DocumentFilters = {
  keyword: '',
  fileType: '',
  status: '',
  spaceId: '',
  classificationDepartmentId: '',
  categoryId: '',
  departmentId: '',
  roleId: '',
  isUnclassified: false,
  page: 1,
  pageSize: 20,
};

const EMPTY_PAGINATION: Pagination = {
  page: 1,
  pageSize: 20,
  totalItems: 0,
  totalPages: 0,
};

export function DocumentListPage() {
  const [filters, setFilters] = useState<DocumentFilters>(DEFAULT_FILTERS);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [pagination, setPagination] = useState<Pagination>(EMPTY_PAGINATION);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<KnowledgeDocumentDetail | null>(null);
  const [chunks, setChunks] = useState<DocumentChunk[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<ImportJob | null>(null);
  const [permissionTarget, setPermissionTarget] = useState<KnowledgeDocument | null>(null);
  const [classificationTarget, setClassificationTarget] = useState<
    KnowledgeDocument | KnowledgeDocumentDetail | null
  >(null);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [bulkClassificationOpen, setBulkClassificationOpen] = useState(false);

  useEffect(() => {
    void loadDocuments(filters);
  }, [filters]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setChunks([]);
      return;
    }
    void loadDetail(selectedId);
  }, [selectedId]);

  // After a retry the job runs asynchronously; poll it so the list/detail
  // reflect the final state without a manual refresh.
  useEffect(() => {
    if (!activeJob || !['PENDING', 'RUNNING'].includes(activeJob.status)) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      getImportJob(activeJob.id)
        .then((job) => {
          setActiveJob(job);
          if (!['PENDING', 'RUNNING'].includes(job.status)) {
            void loadDocuments(filters);
            if (job.documentId) {
              void loadDetail(job.documentId);
            }
          }
        })
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [activeJob, filters]);

  async function loadDocuments(nextFilters = filters) {
    setListLoading(true);
    setListError(null);
    try {
      const result = await listDocuments(nextFilters);
      setDocuments(result.data);
      setPagination(result.pagination);
      setSelectedDocumentIds((current) =>
        current.filter((id) => result.data.some((document) => document.id === id)),
      );
      if (!selectedId && result.data.length) {
        setSelectedId(result.data[0].id);
      }
    } catch (caught) {
      setListError(errorMessage(caught, '请求失败。'));
    } finally {
      setListLoading(false);
    }
  }

  async function loadDetail(documentId = selectedId) {
    if (!documentId) {
      return;
    }
    setDetailLoading(true);
    setDetailError(null);
    try {
      const [detailResult, chunkResult] = await Promise.all([
        getDocument(documentId),
        listDocumentChunks(documentId),
      ]);
      setDetail(detailResult);
      setChunks(chunkResult.data);
    } catch (caught) {
      setDetailError(errorMessage(caught, '请求失败。'));
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleRetry(document: KnowledgeDocument | KnowledgeDocumentDetail) {
    if (!document.latestJob?.retryable) {
      return;
    }
    const failedStage = document.latestJob.failedStage || document.latestJob.stage;
    if (!window.confirm(`确认重试 ${failedStage} 阶段？`)) {
      return;
    }
    try {
      const job = await retryImportJob(document.latestJob.id);
      setActiveJob(job);
      await loadDocuments(filters);
      if (document.id === selectedId) {
        await loadDetail(document.id);
      }
    } catch (caught) {
      setDetailError(errorMessage(caught, '请求失败。'));
    }
  }

  async function handleDelete(document: KnowledgeDocument | KnowledgeDocumentDetail) {
    if (!window.confirm(`确认删除「${document.title}」？该文档将不再参与新检索。`)) {
      return;
    }
    try {
      await deleteDocument(document.id);
      if (selectedId === document.id) {
        setSelectedId(null);
        setDetail(null);
        setChunks([]);
      }
      await loadDocuments(filters);
    } catch (caught) {
      setDetailError(errorMessage(caught, '请求失败。'));
    }
  }

  async function refreshAfterPermissionSaved() {
    setPermissionTarget(null);
    await loadDocuments(filters);
    if (selectedId) {
      await loadDetail(selectedId);
    }
  }

  async function handleClassificationUpdated() {
    setClassificationTarget(null);
    await loadDocuments(filters);
    if (selectedId) {
      await loadDetail(selectedId);
    }
  }

  async function handleBulkClassificationSaved() {
    setBulkClassificationOpen(false);
    setSelectedDocumentIds([]);
    await Promise.all([
      loadDocuments(filters),
      listKnowledgeSpaceStats(),
      listKnowledgeCategoryStats(),
    ]);
    if (selectedId) {
      await loadDetail(selectedId);
    }
  }

  const selectedDocuments = documents.filter((document) =>
    selectedDocumentIds.includes(document.id),
  );

  return (
    <div className="page-stack">
      <section className="toolbar-row">
        <div>
          <p className="eyebrow">知识库中心</p>
          <h2>文档列表</h2>
        </div>
        <a className="secondary-link" href="#knowledge">
          返回知识库中心
        </a>
      </section>

      <section className="knowledge-main">
        <DocumentList
          documents={documents}
          error={listError}
          filters={filters}
          loading={listLoading}
          onDelete={(document) => void handleDelete(document)}
          onEditPermissions={setPermissionTarget}
          onFiltersChange={setFilters}
          onOpenBulkClassification={() => setBulkClassificationOpen(true)}
          onRefresh={() => void loadDocuments(filters)}
          onRetry={(document) => void handleRetry(document)}
          onSelect={setSelectedId}
          onSelectedDocumentIdsChange={setSelectedDocumentIds}
          pagination={pagination}
          selectedDocumentIds={selectedDocumentIds}
          selectedId={selectedId}
        />
        <DocumentDetailPanel
          chunks={chunks}
          detail={detail}
          error={detailError}
          loading={detailLoading}
          onDelete={(document) => void handleDelete(document)}
          onEditPermissions={setPermissionTarget}
          onEditClassification={setClassificationTarget}
          onJobUpdated={setActiveJob}
          onRefresh={() => void loadDetail()}
          onRetry={(document) => void handleRetry(document)}
        />
      </section>

      <DocumentPermissionModal
        document={permissionTarget}
        onClose={() => setPermissionTarget(null)}
        onSaved={() => void refreshAfterPermissionSaved()}
      />
      <DocumentClassificationModal
        document={classificationTarget}
        onClose={() => setClassificationTarget(null)}
        onSaved={() => void handleClassificationUpdated()}
      />
      {bulkClassificationOpen ? (
        <BulkDocumentClassificationModal
          documents={selectedDocuments}
          onClose={() => setBulkClassificationOpen(false)}
          onSaved={() => void handleBulkClassificationSaved()}
        />
      ) : null}
    </div>
  );
}
