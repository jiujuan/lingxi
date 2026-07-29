import type { ApiCallLog } from '../types';

type Props = {
  logs: ApiCallLog[];
};

export function ApiCallLogTable({ logs }: Props) {
  return (
    <section className="panel management-list-panel">
      <div className="management-list-heading">
        <h3>调用日志</h3>
      </div>
      <div aria-label="调用日志" className="management-list api-call-log-list" role="table">
        <div className="management-list-head" role="row">
          <span role="columnheader">请求路径</span>
          <span role="columnheader">Key 前缀</span>
          <span role="columnheader">HTTP 状态</span>
          <span role="columnheader">耗时</span>
          <span role="columnheader">请求 ID</span>
        </div>
        {logs.length === 0 ? <p className="management-list-empty">暂无调用日志</p> : null}
        {logs.map((log) => (
          <div className="management-list-row" key={log.id} role="row">
            <div className="management-list-primary" role="cell">
              <strong>{log.method}</strong>
              <span>{log.path}</span>
            </div>
            <span className="management-list-cell" role="cell">
              {log.keyPrefix || '-'}
            </span>
            <span
              className={`status-tag status-${log.statusCode >= 400 ? 'failed' : 'ready'}`}
              role="cell"
            >
              {log.statusCode}
            </span>
            <span className="management-list-cell" role="cell">
              {log.latencyMs}ms
            </span>
            <span className="management-list-cell" role="cell">
              {log.requestId || '-'}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
