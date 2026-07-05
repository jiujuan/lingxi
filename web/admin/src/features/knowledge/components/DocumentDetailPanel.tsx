import type { DocumentChunk, KnowledgeDocumentDetail } from '../api/documentApi';
import type { ImportJob } from '../api/importJobApi';
import { PermissionGate } from '../../../auth/PermissionGate';
import { formatDateTime } from '../../../shared/format';
import { ImportJobTimeline } from './ImportJobTimeline';
import { QaPairList } from './QaPairList';

type Props = {
  detail: KnowledgeDocumentDetail | null;
  chunks: DocumentChunk[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  onEditPermissions: (document: KnowledgeDocumentDetail) => void;
  onDelete: (document: KnowledgeDocumentDetail) => void;
  onRetry: (document: KnowledgeDocumentDetail) => void;
  onJobUpdated: (job: ImportJob) => void;
};

export function DocumentDetailPanel({
  detail,
  chunks,
  loading,
  error,
  onRefresh,
  onEditPermissions,
  onDelete,
  onRetry,
  onJobUpdated,
}: Props) {
  if (!detail && loading) {
    return (
      <section className="panel detail-panel">
        <p className="muted">正在加载文档详情...</p>
      </section>
    );
  }

  if (!detail) {
    return (
      <section className="panel detail-panel">
        <div className="empty-state">
          <strong>选择一个文档查看详情</strong>
          <p>详情中会展示原文片段、QA 对、权限范围和处理日志。</p>
        </div>
        {error ? <p className="error">{error}</p> : null}
      </section>
    );
  }

  return (
    <section className="panel detail-panel">
      <div className="toolbar-row compact">
        <div>
          <p className="eyebrow">
            {detail.fileType} · {detail.status}
          </p>
          <h3>{detail.title}</h3>
          <p className="muted">{detail.fileName || detail.objectKey}</p>
        </div>
        <div className="button-row">
          <button onClick={onRefresh} type="button">
            刷新
          </button>
          <PermissionGate permission="DOCUMENT_PERMISSION_WRITE">
            <button onClick={() => onEditPermissions(detail)} type="button">
              编辑权限
            </button>
          </PermissionGate>
          {detail.latestJob?.retryable ? (
            <PermissionGate permission="TASK_RETRY">
              <button onClick={() => onRetry(detail)} type="button">
                重试失败阶段
              </button>
            </PermissionGate>
          ) : null}
          <PermissionGate permission="DOCUMENT_DELETE">
            <button className="danger-button" onClick={() => onDelete(detail)} type="button">
              删除
            </button>
          </PermissionGate>
        </div>
      </div>

      {error ? <p className="error">{error}</p> : null}

      <div className="detail-grid">
        <div>
          <span className="field-label">权限范围</span>
          <strong>{permissionText(detail.permissions)}</strong>
        </div>
        <div>
          <span className="field-label">解析器</span>
          <strong>
            {detail.parserName || '-'} {detail.parserVersion || ''}
          </strong>
        </div>
        <div>
          <span className="field-label">QA / Chunk</span>
          <strong>
            {detail.qaPairCount} / {detail.chunkCount}
          </strong>
        </div>
        <div>
          <span className="field-label">更新时间</span>
          <strong>{formatDateTime(detail.updatedAt)}</strong>
        </div>
      </div>

      {detail.lastErrorMessage ? (
        <div className="error-box">
          <strong>{detail.lastErrorCode}</strong>
          <p>{detail.lastErrorMessage}</p>
        </div>
      ) : null}

      <section className="detail-section">
        <h3>任务状态</h3>
        <ImportJobTimeline job={detail.latestJob} />
      </section>

      <section className="detail-section">
        <h3>原文片段</h3>
        {chunks.length ? (
          <div className="chunk-list">
            {chunks.map((chunk) => (
              <article className="chunk-row" key={chunk.id}>
                <div className="toolbar-row compact">
                  <strong>
                    #{chunk.chunkIndex + 1} {chunk.titlePath.join(' / ') || '未命名片段'}
                  </strong>
                  <span>page {chunk.pageNo ?? '-'}</span>
                </div>
                <p>{chunk.content}</p>
              </article>
            ))}
          </div>
        ) : (
          <p className="muted">暂无原文片段。</p>
        )}
      </section>

      <QaPairList documentId={detail.id} onJobUpdated={onJobUpdated} />

      <section className="detail-section">
        <h3>处理日志</h3>
        {detail.processingLogs.length ? (
          <div className="log-list">
            {detail.processingLogs.map((log) => (
              <div className="log-row" key={log.id}>
                <strong>{log.taskType}</strong>
                <span>
                  {log.status} · {log.stage || '-'}
                </span>
                {log.requestId ? (
                  <a href={`#logs?requestId=${log.requestId}`}>
                    <code>{log.requestId}</code>
                  </a>
                ) : (
                  <code>-</code>
                )}
                {log.error ? (
                  <p className="error">
                    {String(log.error.message || log.error.code || '任务失败')}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <p className="muted">暂无处理日志。</p>
        )}
      </section>
    </section>
  );
}

function permissionText(permission: KnowledgeDocumentDetail['permissions']) {
  if (permission.allAuthenticated) {
    return '全部登录用户';
  }
  const parts = [
    permission.departments.map((item) => item.name).join('、'),
    permission.roles.map((item) => item.name).join('、'),
    permission.users.map((item) => item.name).join('、'),
  ].filter(Boolean);
  return parts.join(' / ') || '仅系统管理员';
}
