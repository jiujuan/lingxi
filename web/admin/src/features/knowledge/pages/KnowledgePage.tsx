import { useCallback, useEffect, useState } from 'react';

import { errorMessage } from '../../../api/client';
import {
  getDocumentProcessingSummary,
  listDocuments,
  type DocumentFilters,
  type DocumentProcessingSummary,
  type KnowledgeDocument,
  type Pagination,
} from '../api/documentApi';
import { getImportJob, retryImportJob, type ImportJob } from '../api/importJobApi';
import { DocumentProcessingList } from '../components/DocumentProcessingList';
import { DocumentUploadPanel } from '../components/DocumentUploadPanel';
import { ImportJobTimeline } from '../components/ImportJobTimeline';

const INITIAL_FILTERS: DocumentFilters = {
  keyword: '',
  fileType: '',
  status: '',
  spaceId: '',
  classificationDepartmentId: '',
  categoryId: '',
  isUnclassified: false,
  departmentId: '',
  roleId: '',
  page: 1,
  pageSize: 10,
};

const EMPTY_PAGINATION: Pagination = {
  page: 1,
  pageSize: 10,
  totalItems: 0,
  totalPages: 0,
};

export function KnowledgePage() {
  const [activeJob, setActiveJob] = useState<ImportJob | null>(null);
  const [summary, setSummary] = useState<DocumentProcessingSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [filters, setFilters] = useState<DocumentFilters>(INITIAL_FILTERS);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [pagination, setPagination] = useState<Pagination>(EMPTY_PAGINATION);
  const [documentsLoading, setDocumentsLoading] = useState(true);
  const [documentsError, setDocumentsError] = useState<string | null>(null);

  const loadSummary = useCallback(async () => {
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      setSummary(await getDocumentProcessingSummary());
    } catch (caught) {
      setSummaryError(errorMessage(caught, '文档统计加载失败。'));
    } finally {
      setSummaryLoading(false);
    }
  }, []);

  const loadDocuments = useCallback(async (nextFilters: DocumentFilters) => {
    setFilters(nextFilters);
    setDocumentsLoading(true);
    setDocumentsError(null);
    try {
      const result = await listDocuments(nextFilters);
      setDocuments(result.data);
      setPagination(result.pagination);
    } catch (caught) {
      setDocumentsError(errorMessage(caught, '文档列表加载失败。'));
    } finally {
      setDocumentsLoading(false);
    }
  }, []);

  const refreshWorkspace = useCallback(
    async (nextFilters: DocumentFilters) => {
      await Promise.all([loadSummary(), loadDocuments(nextFilters)]);
    },
    [loadDocuments, loadSummary],
  );

  useEffect(() => {
    void refreshWorkspace(INITIAL_FILTERS);
  }, [refreshWorkspace]);

  useEffect(() => {
    if (!activeJob || !['PENDING', 'RUNNING'].includes(activeJob.status)) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      getImportJob(activeJob.id)
        .then((job) => {
          setActiveJob(job);
          if (!['PENDING', 'RUNNING'].includes(job.status)) {
            void refreshWorkspace({ ...filters, page: 1 });
          }
        })
        .catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [activeJob, filters, refreshWorkspace]);

  function handleUploaded(job: ImportJob) {
    setActiveJob(job);
    void refreshWorkspace({ ...filters, page: 1 });
  }

  async function handleRetry() {
    if (!activeJob?.retryable) {
      return;
    }
    try {
      setActiveJob(await retryImportJob(activeJob.id));
    } catch (caught) {
      setDocumentsError(errorMessage(caught, '重试任务失败。'));
    }
  }

  return (
    <div className="page-stack document-processing-page">
      <header className="document-processing-header">
        <div>
          <p className="eyebrow">知识库中心</p>
          <h2>文档解析与知识提炼中心</h2>
          <p className="muted">上传业务文档，自动完成解析、知识切分、QA 问答生成与向量入库。</p>
        </div>
        <div aria-live="polite" className="document-processing-metrics">
          <div className="document-processing-metric">
            <span>已同步文档</span>
            <strong>
              {summaryLoading ? '—' : (summary?.syncedDocumentCount ?? 0).toLocaleString()}
            </strong>
            <small>篇</small>
          </div>
          <div className="document-processing-metric">
            <span>已解析 Chunks</span>
            <strong>
              {summaryLoading ? '—' : (summary?.totalChunkCount ?? 0).toLocaleString()}
            </strong>
            <small>个</small>
          </div>
          {summaryError ? (
            <p className="error document-processing-summary-error">{summaryError}</p>
          ) : null}
        </div>
      </header>

      <div className="document-processing-shortcuts" aria-label="文档管理快捷入口">
        <button onClick={() => (window.location.hash = '#documents')} type="button">
          查看完整文档管理
        </button>
        <button onClick={() => (window.location.hash = '#knowledge-classification')} type="button">
          管理知识库分类
        </button>
      </div>

      <div className="document-processing-workspace">
        <DocumentUploadPanel onUploaded={handleUploaded} />
        <section
          className="panel document-processing-pipeline"
          aria-labelledby="processing-pipeline-title"
        >
          <div>
            <p className="eyebrow">任务处理流水线</p>
            <h3 id="processing-pipeline-title">从原始文档到可检索知识</h3>
          </div>
          <ImportJobTimeline job={activeJob} onRetry={handleRetry} />
        </section>
      </div>

      <DocumentProcessingList
        documents={documents}
        error={documentsError}
        keyword={filters.keyword}
        loading={documentsLoading}
        onKeywordChange={(keyword) => void loadDocuments({ ...filters, keyword, page: 1 })}
        onPageChange={(page) => void loadDocuments({ ...filters, page })}
        onRefresh={() => void refreshWorkspace(filters)}
        pagination={pagination}
      />
    </div>
  );
}
