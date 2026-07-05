import type { ApiCallLog } from '../types';

type Props = {
  logs: ApiCallLog[];
};

export function ApiCallLogTable({ logs }: Props) {
  return (
    <section className="panel">
      <h3>调用日志</h3>
      <div className="table-list">
        {logs.length === 0 ? <p className="muted">暂无调用日志</p> : null}
        {logs.map((log) => (
          <div className="api-log-row" key={log.id}>
            <strong>{log.method}</strong>
            <span>{log.path}</span>
            <code>{log.keyPrefix || '-'}</code>
            <span>{log.statusCode}</span>
            <span>{log.latencyMs}ms</span>
            <code>{log.requestId || '-'}</code>
          </div>
        ))}
      </div>
    </section>
  );
}
