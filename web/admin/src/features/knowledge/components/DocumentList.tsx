import type { DocumentFilters, KnowledgeDocument, Pagination } from '../api/documentApi';

type Props = {
  documents: KnowledgeDocument[];
  pagination: Pagination;
  filters: DocumentFilters;
  selectedId: string | null;
  loading: boolean;
  error: string | null;
  onFiltersChange: (filters: DocumentFilters) => void;
  onRefresh: () => void;
  onSelect: (documentId: string) => void;
  onEditPermissions: (document: KnowledgeDocument) => void;
  onDelete: (document: KnowledgeDocument) => void;
  onRetry: (document: KnowledgeDocument) => void;
};

const STATUS_OPTIONS = ['', 'UPLOADED', 'PARSING', 'QA_SPLITTING', 'EMBEDDING', 'READY', 'FAILED'];
const TYPE_OPTIONS = ['', 'MARKDOWN', 'TEXT', 'PDF', 'DOCX'];

export function DocumentList({
  documents,
  pagination,
  filters,
  selectedId,
  loading,
  error,
  onFiltersChange,
  onRefresh,
  onSelect,
  onEditPermissions,
  onDelete,
  onRetry,
}: Props) {
  function changeFilter(key: keyof DocumentFilters, value: string) {
    onFiltersChange({ ...filters, [key]: value, page: 1 });
  }

  function changePage(offset: number) {
    onFiltersChange({
      ...filters,
      page: Math.max(1, Math.min(pagination.totalPages || 1, filters.page + offset)),
    });
  }

  return (
    <section className="panel document-list-panel">
      <div className="toolbar-row compact">
        <div>
          <h3>文档列表</h3>
          <p className="muted">按状态、类型和权限范围筛选已入库文档。</p>
        </div>
        <button onClick={onRefresh} type="button">
          刷新
        </button>
      </div>

      <div className="filter-grid">
        <label>
          关键词
          <input
            onChange={(event) => changeFilter('keyword', event.target.value)}
            placeholder="标题或文件名"
            value={filters.keyword}
          />
        </label>
        <label>
          类型
          <select onChange={(event) => changeFilter('fileType', event.target.value)} value={filters.fileType}>
            {TYPE_OPTIONS.map((item) => (
              <option key={item || 'ALL'} value={item}>
                {item || '全部类型'}
              </option>
            ))}
          </select>
        </label>
        <label>
          状态
          <select onChange={(event) => changeFilter('status', event.target.value)} value={filters.status}>
            {STATUS_OPTIONS.map((item) => (
              <option key={item || 'ALL'} value={item}>
                {item || '全部状态'}
              </option>
            ))}
          </select>
        </label>
        <label>
          部门 ID
          <input
            onChange={(event) => changeFilter('departmentId', event.target.value)}
            placeholder="department id"
            value={filters.departmentId}
          />
        </label>
        <label>
          角色 ID
          <input
            onChange={(event) => changeFilter('roleId', event.target.value)}
            placeholder="role id"
            value={filters.roleId}
          />
        </label>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {loading ? <p className="muted">正在加载文档列表...</p> : null}
      {!loading && !documents.length ? (
        <div className="empty-state">
          <strong>暂无匹配文档</strong>
          <p>调整筛选条件，或上传第一份 Markdown/TXT 文档。</p>
        </div>
      ) : null}

      {documents.length ? (
        <div className="document-table" role="table" aria-label="文档列表">
          <div className="document-table-head" role="row">
            <span>文档</span>
            <span>状态</span>
            <span>权限</span>
            <span>QA/Chunk</span>
            <span>更新时间</span>
            <span>操作</span>
          </div>
          {documents.map((document) => (
            <div
              className={selectedId === document.id ? 'document-row selected' : 'document-row'}
              key={document.id}
              role="row"
            >
              <button className="link-button title-button" onClick={() => onSelect(document.id)} type="button">
                <strong>{document.title}</strong>
                <span>{document.fileName || '未绑定文件'} · {formatBytes(document.fileSize)}</span>
              </button>
              <span className={`status-tag status-${document.status.toLowerCase()}`}>
                {stageLabel(document.status)}
              </span>
              <span>{permissionText(document.permissions)}</span>
              <span>{document.qaPairCount} / {document.chunkCount}</span>
              <span>{formatTime(document.updatedAt)}</span>
              <div className="button-row table-actions">
                <button onClick={() => onSelect(document.id)} type="button">
                  查看
                </button>
                <button onClick={() => onEditPermissions(document)} type="button">
                  权限
                </button>
                {document.latestJob?.retryable ? (
                  <button onClick={() => onRetry(document)} type="button">
                    重试
                  </button>
                ) : null}
                <button className="danger-button" onClick={() => onDelete(document)} type="button">
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : null}

      <div className="pagination-row">
        <span>
          第 {pagination.page} / {pagination.totalPages || 1} 页，共 {pagination.totalItems} 条
        </span>
        <div className="button-row">
          <button disabled={filters.page <= 1} onClick={() => changePage(-1)} type="button">
            上一页
          </button>
          <button
            disabled={!pagination.totalPages || filters.page >= pagination.totalPages}
            onClick={() => changePage(1)}
            type="button"
          >
            下一页
          </button>
        </div>
      </div>
    </section>
  );
}

function permissionText(permission: KnowledgeDocument['permissions']) {
  if (permission.allAuthenticated) {
    return '全部登录用户';
  }
  const parts = [
    permission.departments.length ? `${permission.departments.length} 部门` : '',
    permission.roles.length ? `${permission.roles.length} 角色` : '',
    permission.users.length ? `${permission.users.length} 用户` : '',
  ].filter(Boolean);
  return parts.join('、') || '仅系统管理员';
}

function stageLabel(status: string) {
  const map: Record<string, string> = {
    UPLOADED: '已上传',
    PARSING: '解析中',
    QA_SPLITTING: 'QA 拆分中',
    EMBEDDING: '向量化中',
    READY: '可问答',
    FAILED: '失败',
    DELETED: '已删除',
  };
  return map[status] || status;
}

function formatBytes(value: number) {
  if (!value) {
    return '0 B';
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatTime(value: string) {
  return new Date(value).toLocaleString();
}
