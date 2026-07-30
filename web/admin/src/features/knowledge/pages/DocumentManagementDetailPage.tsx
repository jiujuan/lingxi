import { useEffect, useState } from "react";

import { errorMessage } from "../../../api/client";
import {
  getDocument,
  listDocumentChunks,
  type DocumentChunk,
  type KnowledgeDocumentDetail,
} from "../api/documentApi";
import { DocumentDetailPanel } from "../components/DocumentDetailPanel";
import type { ImportJob } from "../api/importJobApi";

export function DocumentManagementDetailPage() {
  const [documentId, setDocumentId] = useState(() => readDocumentId());
  const [detail, setDetail] = useState<KnowledgeDocumentDetail | null>(null);
  const [chunks, setChunks] = useState<DocumentChunk[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [, setActiveJob] = useState<ImportJob | null>(null);

  useEffect(() => {
    const onHashChange = () => setDocumentId(readDocumentId());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    if (!documentId) {
      setDetail(null);
      setChunks([]);
      setError("未找到要查看的文档。");
      return;
    }
    void loadDetail(documentId);
  }, [documentId]);

  async function loadDetail(id = documentId) {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const [detailResult, chunkResult] = await Promise.all([
        getDocument(id),
        listDocumentChunks(id),
      ]);
      setDetail(detailResult);
      setChunks(chunkResult.data);
    } catch (caught) {
      setError(errorMessage(caught, "文档详情加载失败。"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page-stack document-management-detail-page">
      <header className="document-management-detail-header">
        <div>
          <p className="eyebrow">文档管理</p>
          <h2>{detail?.title || "文档详情"}</h2>
          <p className="muted">查看文档解析状态、原文片段、QA 对与处理日志</p>
        </div>
        <div className="button-row">
          <a className="secondary-link" href="#document-management">
            返回文档管理
          </a>
          <button onClick={() => void loadDetail()} type="button">
            刷新
          </button>
        </div>
      </header>

      <DocumentDetailPanel
        chunks={chunks}
        detail={detail}
        error={error}
        hideToolbar
        loading={loading}
        onDelete={() => undefined}
        onEditClassification={() => undefined}
        onEditPermissions={() => undefined}
        onJobUpdated={setActiveJob}
        onRefresh={() => void loadDetail()}
        onRetry={() => undefined}
      />
    </div>
  );
}

function readDocumentId() {
  const query = window.location.hash.split("?")[1] || "";
  return new URLSearchParams(query).get("documentId");
}
