type Props = {
  title: string;
  payload: unknown;
  onClose: () => void;
};

const MODEL_DIAGNOSTIC_FIELDS: Array<[string, string]> = [
  ['runId', 'Run ID'],
  ['batchId', 'Batch ID'],
  ['batchIndex', 'Batch index'],
  ['retryCount', 'Retry count'],
  ['splitDepth', 'Split depth'],
  ['inputCharCount', '输入字符数'],
  ['estimatedInputTokens', '输入 Tokens 估算'],
  ['outputCharCount', '输出字符数'],
  ['estimatedOutputTokens', '输出 Tokens 估算'],
  ['timeoutPhase', 'Timeout phase'],
  ['endpoint', 'Endpoint'],
  ['modelNameSnapshot', '模型快照'],
  ['errorCode', '错误码'],
  ['errorMessage', '错误信息'],
];

function isModelCallPayload(payload: unknown): payload is Record<string, unknown> {
  return (
    typeof payload === 'object' &&
    payload !== null &&
    ('batchId' in payload || 'timeoutPhase' in payload || 'estimatedInputTokens' in payload)
  );
}

export function LogDetailDrawer({ title, payload, onClose }: Props) {
  if (!payload) {
    return null;
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section aria-modal="true" className="modal-panel log-detail-drawer" role="dialog">
        <div className="toolbar-row compact">
          <h3>{title}</h3>
          <button className="secondary-button" onClick={onClose} type="button">
            关闭
          </button>
        </div>
        {isModelCallPayload(payload) ? (
          <dl className="model-connection-diagnostics">
            {MODEL_DIAGNOSTIC_FIELDS.map(([key, label]) => (
              <div key={key}>
                <dt>{label}</dt>
                <dd>{payload[key] == null ? '-' : String(payload[key])}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        <pre>{JSON.stringify(payload, null, 2)}</pre>
      </section>
    </div>
  );
}
