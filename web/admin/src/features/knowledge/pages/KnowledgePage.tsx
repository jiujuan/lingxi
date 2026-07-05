import { useEffect, useState } from 'react';

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
import { getImportJob, retryImportJob, type ImportJob } from '../api/importJobApi';
import { DocumentDetailPanel } from '../components/DocumentDetailPanel';
import { DocumentList } from '../components/DocumentList';
import { DocumentPermissionModal } from '../components/DocumentPermissionModal';
import { DocumentUploadPanel } from '../components/DocumentUploadPanel';
import { ImportJobTimeline } from '../components/ImportJobTimeline';

const DEFAULT_FILTERS: DocumentFilters = {
  keyword: '',
  fileType: '',
  status: '',
  departmentId: '',
  roleId: '',
  page: 1,
  pageSize: 20,
};

const EMPTY_PAGINATION: Pagination = {
  page: 1,
  pageSize: 20,
  totalItems: 0,
  totalPages: 0,
};

export function KnowledgePage() {
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

  useEffect(() => {
    if (!activeJob || !['PENDING', 'RUNNING'].includes(activeJob.status)) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      getImportJob(activeJob.id)
        .then((job) => {
          setActiveJob(job);
          if (job.documentId) {
            setSelectedId(job.documentId);
          }
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
      if (!selectedId && result.data.length) {
        setSelectedId(result.data[0].id);
      }
    } catch (caught) {
      setListError(readError(caught));
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
      setDetailError(readError(caught));
    } finally {
      setDetailLoading(false);
    }
  }

  function handleUploaded(job: ImportJob) {
    setActiveJob(job);
    if (job.documentId) {
      setSelectedId(job.documentId);
    }
    void loadDocuments(filters);
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
      setDetailError(readError(caught));
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
      setDetailError(readError(caught));
    }
  }

  async function refreshAfterPermissionSaved() {
    setPermissionTarget(null);
    await loadDocuments(filters);
    if (selectedId) {
      await loadDetail(selectedId);
    }
  }

  return (
    <div className="page-stack">
      <section className="toolbar-row">
        <div>
          <p className="eyebrow">知识库中心</p>
          <h2>文档入库、权限和 QA 结果</h2>
        </div>
        <span className="status-pill">V1.1 入库闭环</span>
      </section>

      <section className="knowledge-grid">
        <DocumentUploadPanel onUploaded={handleUploaded} />
        <section className="panel">
          <h3>最近任务</h3>
          <ImportJobTimeline job={activeJob} />
        </section>
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
          onRefresh={() => void loadDocuments(filters)}
          onRetry={(document) => void handleRetry(document)}
          onSelect={setSelectedId}
          pagination={pagination}
          selectedId={selectedId}
        />
        <DocumentDetailPanel
          chunks={chunks}
          detail={detail}
          error={detailError}
          loading={detailLoading}
          onDelete={(document) => void handleDelete(document)}
          onEditPermissions={setPermissionTarget}
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
    </div>
  );
}

function readError(error: unknown) {
  if (typeof error === 'object' && error && 'error' in error) {
    const payload = error as { error?: { message?: string } };
    return payload.error?.message || '请求失败。';
  }
  return '请求失败。';
}
