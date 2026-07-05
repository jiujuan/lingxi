import type { RetrievalExplanation } from '../types';

const STAGES = [
  ['vector', '向量召回'],
  ['text', '全文召回'],
  ['rrf', 'RRF 融合'],
  ['rerank', 'ReRank'],
] as const;

type Props = {
  explanation: RetrievalExplanation | null;
  onLoad: () => void;
  isLoading: boolean;
};

export function RetrievalExplanationPanel({ explanation, isLoading, onLoad }: Props) {
  return (
    <section className="retrieval-panel panel">
      <div className="toolbar-row compact">
        <h3>检索解释</h3>
        <button className="secondary-button" disabled={isLoading} onClick={onLoad} type="button">
          查看
        </button>
      </div>
      {!explanation ? <p className="muted">选择一次回答后可查看四阶段候选和分数。</p> : null}
      {explanation
        ? STAGES.map(([key, label]) => (
            <div className="explain-stage" key={key}>
              <strong>{label}</strong>
              {(explanation.stages[key] || []).length === 0 ? <span className="muted">无候选</span> : null}
              {(explanation.stages[key] || []).slice(0, 3).map((item, index) => (
                <div className="explain-row" key={`${key}-${index}`}>
                  <span>{String(item.question || item.qaPairId || '-')}</span>
                  <code>{String(item.rerankScore || item.rrfScore || item.score || '-')}</code>
                </div>
              ))}
            </div>
          ))
        : null}
    </section>
  );
}
