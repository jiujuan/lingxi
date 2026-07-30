import { useEffect, useState } from "react";

import { errorMessage } from "../../../api/client";
import { PermissionGate } from "../../../auth/PermissionGate";
import {
  deleteDocument,
  listDocuments,
  type DocumentFilters,
  type KnowledgeDocument,
  type Pagination,
} from "../api/documentApi";
import { listKnowledgeSpaces } from "../api/classificationApi";
import { DocumentClassificationModal } from "../components/DocumentClassificationModal";
import { DocumentPermissionModal } from "../components/DocumentPermissionModal";
import type { KnowledgeSpace } from "../types/classification";

const DEFAULT_FILTERS: DocumentFilters = {
  keyword: "",
  fileType: "",
  status: "",
  spaceId: "",
  classificationDepartmentId: "",
  categoryId: "",
  isUnclassified: false,
  departmentId: "",
  roleId: "",
  page: 1,
  pageSize: 10,
};

const EMPTY_PAGINATION: Pagination = {
  page: 1,
  pageSize: 10,
  totalItems: 0,
  totalPages: 0,
};

const STATUS_TABS = [
  { label: "全部状态", value: "" },
  { label: "已发布", value: "READY" },
  { label: "解析中", value: "PARSING" },
  { label: "待审核", value: "UPLOADED" },
  { label: "解析失败", value: "FAILED" },
];

export function DocumentManagementPage() {
  const [filters, setFilters] = useState<DocumentFilters>(DEFAULT_FILTERS);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [pagination, setPagination] = useState<Pagination>(EMPTY_PAGINATION);
  const [spaces, setSpaces] = useState<KnowledgeSpace[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [permissionTarget, setPermissionTarget] =
    useState<KnowledgeDocument | null>(null);
  const [classificationTarget, setClassificationTarget] =
    useState<KnowledgeDocument | null>(null);

  useEffect(() => {
    void loadDocuments(filters);
  }, [filters]);

  useEffect(() => {
    listKnowledgeSpaces()
      .then((result) => setSpaces(result.data))
      .catch(() => undefined);
  }, []);

  async function loadDocuments(nextFilters: DocumentFilters) {
    setLoading(true);
    setError(null);
    try {
      const result = await listDocuments(nextFilters);
      setDocuments(result.data);
      setPagination(result.pagination);
    } catch (caught) {
      setError(errorMessage(caught, "文档列表加载失败。"));
    } finally {
      setLoading(false);
    }
  }

  function updateFilters(next: Partial<DocumentFilters>) {
    setFilters((current) => ({ ...current, ...next, page: next.page ?? 1 }));
  }

  async function handleDelete(document: KnowledgeDocument) {
    if (
      !window.confirm(`确认删除「${document.title}」？该文档将不再参与新检索。`)
    ) {
      return;
    }
    try {
      await deleteDocument(document.id);
      await loadDocuments(filters);
    } catch (caught) {
      setError(errorMessage(caught, "文档删除失败。"));
    }
  }

  function openDetail(documentId: string) {
    window.location.hash = `#document-management-detail?documentId=${encodeURIComponent(documentId)}`;
  }

  function changePage(offset: number) {
    updateFilters({
      page: Math.max(
        1,
        Math.min(pagination.totalPages || 1, filters.page + offset),
      ),
    });
  }

  return (
    <div className="page-stack document-management-page">
      <header className="document-management-header">
        <div>
          <p className="eyebrow">知识库中心</p>
          <h2>文档管理</h2>
          <p className="muted">
            文档上传、智能解析、向量切片与版本全生命周期管理
          </p>
        </div>
        <a className="secondary-link" href="#knowledge">
          上传文档
        </a>
      </header>

      <section className="panel management-list-panel document-management-list">
        <div className="document-management-toolbar">
          <div
            className="document-management-tabs"
            role="tablist"
            aria-label="文档状态筛选"
          >
            {STATUS_TABS.map((tab) => (
              <button
                aria-selected={filters.status === tab.value}
                className={
                  filters.status === tab.value
                    ? "document-management-tab active"
                    : "document-management-tab"
                }
                key={tab.value || "all"}
                onClick={() => updateFilters({ status: tab.value })}
                role="tab"
                type="button"
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="document-management-filters">
            <label className="document-management-search">
              <span className="sr-only">搜索文档名称</span>
              <svg aria-hidden="true" viewBox="0 0 24 24">
                <circle cx="11" cy="11" r="6" />
                <path d="m16 16 4 4" />
              </svg>
              <input
                aria-label="搜索文档名称"
                onChange={(event) =>
                  updateFilters({ keyword: event.target.value })
                }
                placeholder="搜索文档名称..."
                value={filters.keyword}
              />
            </label>
            <label className="document-management-space-select">
              <span className="sr-only">知识库筛选</span>
              <select
                aria-label="知识库筛选"
                onChange={(event) =>
                  updateFilters({ spaceId: event.target.value })
                }
                value={filters.spaceId}
              >
                <option value="">全部知识库</option>
                {spaces.map((space) => (
                  <option key={space.id} value={space.id}>
                    {space.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              aria-label="刷新文档列表"
              className="document-management-refresh"
              onClick={() => void loadDocuments(filters)}
              type="button"
            >
              刷新
            </button>
          </div>
        </div>

        {error ? (
          <p className="error document-management-error">{error}</p>
        ) : null}
        {loading ? (
          <p className="muted document-management-loading">正在加载文档...</p>
        ) : null}

        <div
          className="management-list document-management-table"
          role="table"
          aria-label="文档管理列表"
        >
          <div className="management-list-head" role="row">
            <span>文档名称</span>
            <span>知识库</span>
            <span>标签</span>
            <span>解析进度</span>
            <span>版本</span>
            <span>状态</span>
            <span>操作</span>
          </div>
          {!loading && !documents.length ? (
            <p className="management-list-empty" role="status">
              暂无符合条件的文档
            </p>
          ) : null}
          {documents.map((document) => (
            <DocumentManagementRow
              document={document}
              key={document.id}
              onClassification={() => setClassificationTarget(document)}
              onDelete={() => void handleDelete(document)}
              onPermission={() => setPermissionTarget(document)}
              onView={() => openDetail(document.id)}
            />
          ))}
        </div>

        <div className="pagination-row document-management-pagination">
          <span>
            第 {pagination.page} / {pagination.totalPages || 1} 页，共{" "}
            {pagination.totalItems} 条
          </span>
          <div className="button-row">
            <button
              disabled={filters.page <= 1 || loading}
              onClick={() => changePage(-1)}
              type="button"
            >
              上一页
            </button>
            <button
              disabled={
                !pagination.totalPages ||
                filters.page >= pagination.totalPages ||
                loading
              }
              onClick={() => changePage(1)}
              type="button"
            >
              下一页
            </button>
          </div>
        </div>
      </section>

      <DocumentPermissionModal
        document={permissionTarget}
        onClose={() => setPermissionTarget(null)}
        onSaved={() => {
          setPermissionTarget(null);
          void loadDocuments(filters);
        }}
      />
      <DocumentClassificationModal
        document={classificationTarget}
        onClose={() => setClassificationTarget(null)}
        onSaved={() => {
          setClassificationTarget(null);
          void loadDocuments(filters);
        }}
      />
    </div>
  );
}

type RowProps = {
  document: KnowledgeDocument;
  onView: () => void;
  onPermission: () => void;
  onClassification: () => void;
  onDelete: () => void;
};

function DocumentManagementRow({
  document,
  onView,
  onPermission,
  onClassification,
  onDelete,
}: RowProps) {
  const progress = document.latestJob
    ? Math.max(0, Math.min(100, Math.round(document.latestJob.progress)))
    : document.status === "READY"
      ? 100
      : 0;
  const tags = [
    document.classification?.categoryName,
    document.classification?.departmentName,
  ].filter((item): item is string => Boolean(item));

  return (
    <div className="management-list-row document-management-row" role="row">
      <button
        className="document-management-primary"
        onClick={onView}
        type="button"
      >
        <span
          className={`document-file-icon document-file-icon-${fileTone(document.fileType)}`}
          aria-hidden="true"
        >
          <svg viewBox="0 0 24 24">
            <path d="M6 3h8l4 4v14H6zM14 3v5h5M9 13h6M9 17h5" />
          </svg>
        </span>
        <span className="management-list-primary">
          <strong title={document.title}>{document.title}</strong>
          <span>{fileTypeLabel(document.fileType)}</span>
        </span>
      </button>
      <span className="management-list-cell">
        {document.classification?.spaceName || "未分类知识库"}
      </span>
      <span className="document-management-tags">
        {tags.length ? (
          tags.map((tag) => <span key={tag}>{tag}</span>)
        ) : (
          <span>暂无标签</span>
        )}
      </span>
      <span className="document-management-progress">
        <span
          className="document-management-progress-bar"
          aria-label={`解析进度 ${progress}%`}
        >
          <span style={{ width: `${progress}%` }} />
        </span>
        <span>{progress}%</span>
      </span>
      <span className="management-list-cell document-management-version">
        {document.parserName || "—"}
      </span>
      <span className={`status-tag status-${document.status.toLowerCase()}`}>
        {statusLabel(document.status)}
      </span>
      <div className="management-list-actions document-management-actions">
        <button
          className="management-list-action"
          onClick={onView}
          type="button"
        >
          查看
        </button>
        <PermissionGate permission="DOCUMENT_PERMISSION_WRITE">
          <button
            className="management-list-action"
            onClick={onPermission}
            type="button"
          >
            权限
          </button>
        </PermissionGate>
        <PermissionGate permission="DOCUMENT_WRITE">
          <button
            className="management-list-action"
            onClick={onClassification}
            type="button"
          >
            分类
          </button>
        </PermissionGate>
        <PermissionGate permission="DOCUMENT_DELETE">
          <button
            className="management-list-action danger"
            onClick={onDelete}
            type="button"
          >
            删除
          </button>
        </PermissionGate>
      </div>
    </div>
  );
}

function fileTone(fileType: string) {
  if (fileType === "PDF") return "pdf";
  if (fileType === "XLSX" || fileType === "CSV") return "sheet";
  return "word";
}

function fileTypeLabel(fileType: string) {
  const labels: Record<string, string> = {
    DOCX: "Word",
    PDF: "PDF",
    MARKDOWN: "Markdown",
    TEXT: "Text",
    XLSX: "Excel",
    CSV: "CSV",
  };
  return labels[fileType] || fileType;
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    UPLOADED: "待审核",
    PARSING: "解析中",
    QA_SPLITTING: "解析中",
    EMBEDDING: "解析中",
    READY: "已发布",
    FAILED: "解析失败",
    DELETED: "已删除",
  };
  return labels[status] || status;
}
