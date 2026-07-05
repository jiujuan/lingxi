import type { ChatCitation } from '../types';

type Props = {
  citations: ChatCitation[];
  onOpenSource: (citationId: string) => void;
};

export function CitationPanel({ citations, onOpenSource }: Props) {
  return (
    <aside className="citation-panel panel">
      <h3>引用</h3>
      {citations.length === 0 ? (
        <div className="empty-state">
          <strong>暂无引用</strong>
          <p>有答案的回答会在这里显示引用片段。</p>
        </div>
      ) : null}
      <div className="citation-list">
        {citations.map((citation) => (
          <button
            className="citation-item"
            key={citation.citationId}
            onClick={() => onOpenSource(citation.citationId)}
            type="button"
          >
            <span>#{citation.rank}</span>
            <strong>{citation.title || '引用快照'}</strong>
            <small>
              页码 {citation.pageNo || '-'} · 分数 {citation.score?.toFixed(3) || '-'}
            </small>
            <p>{citation.quote}</p>
            <code>{citation.qaPairId}</code>
          </button>
        ))}
      </div>
    </aside>
  );
}
