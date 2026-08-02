import { useCallback, useEffect, useState } from 'react';

import { listQaPairs, regenerateQaPairs, type ImportJob, type QaPair } from '../api/importJobApi';

type Props = {
  documentId: string | null;
  onJobUpdated: (job: ImportJob) => void;
};

export function QaPairList({ documentId, onJobUpdated }: Props) {
  const [items, setItems] = useState<QaPair[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadItems = useCallback(
    async (nextDocumentId = documentId) => {
      if (!nextDocumentId) {
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const result = await listQaPairs(nextDocumentId);
        setItems(result.data);
      } catch (caught) {
        setError(readError(caught));
      } finally {
        setLoading(false);
      }
    },
    [documentId],
  );

  useEffect(() => {
    if (!documentId) {
      setItems([]);
      return;
    }
    void loadItems(documentId);
  }, [documentId, loadItems]);

  async function regenerate() {
    if (!documentId || !window.confirm('确认重新生成该文档的 QA 对？')) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const job = await regenerateQaPairs(documentId);
      onJobUpdated(job);
      await loadItems(documentId);
    } catch (caught) {
      setError(readError(caught));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="detail-section">
      <div className="toolbar-row compact">
        <h3>QA 对</h3>
        <div className="button-row">
          <button disabled={!documentId || loading} onClick={() => void regenerate()} type="button">
            重新生成
          </button>
          <button disabled={!documentId || loading} onClick={() => void loadItems()} type="button">
            刷新
          </button>
        </div>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {loading ? <p className="muted">正在读取 QA 对...</p> : null}
      {!loading && !items.length ? (
        <p className="muted">暂无 QA 对，解析完成后可重新生成。</p>
      ) : null}
      <div className="qa-list">
        {items.map((item) => (
          <article className="qa-row" key={item.id}>
            <strong>{item.question}</strong>
            <p>{item.answer}</p>
            {item.quote ? <blockquote>{item.quote}</blockquote> : null}
            <span>
              {item.embeddingStatus} · page {item.pageNo ?? '-'}
            </span>
          </article>
        ))}
      </div>
    </section>
  );
}

function readError(error: unknown) {
  if (typeof error === 'object' && error && 'error' in error) {
    const payload = error as { error?: { message?: string } };
    return payload.error?.message || '请求失败。';
  }
  return '请求失败。';
}
