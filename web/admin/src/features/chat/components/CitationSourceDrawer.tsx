import type { CitationSource } from '../types';

type Props = {
  source: CitationSource | null;
  error: string | null;
  onClose: () => void;
};

export function CitationSourceDrawer({ source, error, onClose }: Props) {
  if (!source && !error) {
    return null;
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section aria-label="引用原文" className="modal-panel citation-source-drawer" role="dialog">
        <div className="toolbar-row compact">
          <h3>引用原文</h3>
          <button className="secondary-button" onClick={onClose} type="button">
            关闭
          </button>
        </div>
        {error ? <div className="error-box">{error}</div> : null}
        {source ? (
          <div className="detail-section">
            <div className="detail-grid compact-detail">
              <div>
                <span className="field-label">文档</span>
                <strong>{source.documentTitle || '历史快照'}</strong>
              </div>
              <div>
                <span className="field-label">页码</span>
                <strong>{source.pageNo || '-'}</strong>
              </div>
              <div>
                <span className="field-label">状态</span>
                <strong>{source.documentDeleted ? '文档已删除' : '当前可访问'}</strong>
              </div>
            </div>
            <blockquote>{source.quote}</blockquote>
            <pre>{source.sourceText}</pre>
          </div>
        ) : null}
      </section>
    </div>
  );
}
