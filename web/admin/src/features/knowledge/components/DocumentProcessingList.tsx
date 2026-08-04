import { formatBytes, formatDateTime } from '../../../shared/format';
import type { KnowledgeDocument, Pagination } from '../api/documentApi';

type Props = {
  documents: KnowledgeDocument[];
  pagination: Pagination;
  keyword: string;
  loading: boolean;
  error: string | null;
  onKeywordChange: (keyword: string) => void;
  onRefresh: () => void;
  onPageChange: (page: number) => void;
};

const STATUS_LABELS: Record<string, string> = {
  UPLOADED: '等待解析',
  PARSING: '文档解析中',
  CHUNKING: '知识切片中',
  QA_SPLITTING: 'QA 文档生成中',
  EMBEDDING: '向量化中',
  INDEXING: '知识入库中',
  READY: '已注入向量库',
  FAILED: '解析失败',
};

export function DocumentProcessingList({
  documents,
  pagination,
  keyword,
  loading,
  error,
  onKeywordChange,
  onRefresh,
  onPageChange,
}: Props) {
  return (
    <section className="panel document-processing-list" aria-labelledby="processing-list-title">
      <div className="document-processing-list-header">
        <div>
          <p className="eyebrow">文档处理列表</p>
          <h3 id="processing-list-title">已同步与正在处理的文档</h3>
        </div>
        <div className="document-processing-list-actions">
          <input
            aria-label="检索已同步文档"
            onChange={(event) => onKeywordChange(event.target.value)}
            placeholder="检索文档名称"
            type="search"
            value={keyword}
          />
          <button onClick={onRefresh} type="button">刷新</button>
        </div>
      </div>

      {error ? <p className="error-box" role="alert">{error}</p> : null}
      <div className="document-processing-table" role="table">
        <div className="document-processing-table-head" role="row">
          <span role="columnheader">文档名称与归属</span>
          <span role="columnheader">知识分类空间</span>
          <span role="columnheader">切分 Chunks 数</span>
          <span role="columnheader">同步状态</span>
          <span role="columnheader">管理调试</span>
        </div>
        {loading ? (
          <p className="document-processing-list-state" role="status">正在加载文档处理列表…</p>
        ) : documents.length ? (
          documents.map((document) => (
            <div className="document-processing-table-row" key={document.id} role="row">
              <div className="document-processing-document" role="cell">
                <strong>{document.title}</strong>
                <span>{formatDateTime(document.updatedAt)} · {formatBytes(document.fileSize)}</span>
              </div>
              <span role="cell">{document.classification?.spaceName ?? '未分类知识库'}</span>
              <span role="cell">{document.chunkCount.toLocaleString()}</span>
              <span className={`status-tag status-${document.status.toLowerCase()}`} role="cell">
                {STATUS_LABELS[document.status] ?? document.status}
              </span>
              <span role="cell">
                <button
                  onClick={() => {
                    window.location.hash = `#document-management-detail?documentId=${encodeURIComponent(document.id)}`;
                  }}
                  type="button"
                >
                  查看详情
                </button>
              </span>
            </div>
          ))
        ) : (
          <p className="document-processing-list-state">暂无符合条件的文档。</p>
        )}
      </div>

      <div className="document-processing-pagination">
        <span>共 {pagination.totalItems} 篇文档</span>
        <div>
          <button
            disabled={loading || pagination.page <= 1}
            onClick={() => onPageChange(pagination.page - 1)}
            type="button"
          >
            上一页
          </button>
          <span>{pagination.page} / {pagination.totalPages || 1}</span>
          <button
            disabled={loading || pagination.totalPages === 0 || pagination.page >= pagination.totalPages}
            onClick={() => onPageChange(pagination.page + 1)}
            type="button"
          >
            下一页
          </button>
        </div>
      </div>
    </section>
  );
}
