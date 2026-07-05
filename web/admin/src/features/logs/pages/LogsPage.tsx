import { useEffect, useMemo, useState } from 'react';

import {
  listApiCallLogs,
  listAuditLogs,
  listModelCallLogs,
  listTaskRunLogs,
  retryTaskRun,
} from '../api/logsApi';
import { LogDetailDrawer } from '../components/LogDetailDrawer';
import type { ApiCallLog, AuditLog, LogFilters, ModelCallLog, TaskRunLog } from '../types';

type Tab = 'tasks' | 'models' | 'api' | 'audit';

const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'tasks', label: '任务日志' },
  { id: 'models', label: '模型调用' },
  { id: 'api', label: 'API 调用' },
  { id: 'audit', label: '审计日志' },
];

export function LogsPage() {
  const [tab, setTab] = useState<Tab>('tasks');
  const [filters, setFilters] = useState<LogFilters>(() => initialFilters());
  const [taskLogs, setTaskLogs] = useState<TaskRunLog[]>([]);
  const [modelLogs, setModelLogs] = useState<ModelCallLog[]>([]);
  const [apiLogs, setApiLogs] = useState<ApiCallLog[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [selected, setSelected] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    void refresh();
  }, [tab, filters.page]);

  const currentRows = useMemo(() => {
    if (tab === 'tasks') return taskLogs;
    if (tab === 'models') return modelLogs;
    if (tab === 'api') return apiLogs;
    return auditLogs;
  }, [apiLogs, auditLogs, modelLogs, tab, taskLogs]);

  async function refresh() {
    try {
      if (tab === 'tasks') {
        setTaskLogs((await listTaskRunLogs(filters)).data);
      }
      if (tab === 'models') {
        setModelLogs((await listModelCallLogs(filters)).data);
      }
      if (tab === 'api') {
        setApiLogs((await listApiCallLogs(filters)).data);
      }
      if (tab === 'audit') {
        setAuditLogs((await listAuditLogs(filters)).data);
      }
      setError(null);
    } catch {
      setError('日志加载失败');
    }
  }

  function updateFilter(key: keyof LogFilters, value: string | number) {
    setFilters((current) => ({ ...current, [key]: value, page: key === 'page' ? Number(value) : 1 }));
  }

  async function copyRequestId(requestId: string | null) {
    if (!requestId) return;
    await navigator.clipboard.writeText(requestId);
    setCopied(requestId);
    window.setTimeout(() => setCopied(null), 1200);
  }

  async function retry(log: TaskRunLog) {
    if (!window.confirm(`确认重试任务 ${log.taskType}？`)) {
      return;
    }
    await retryTaskRun(log.id);
    await refresh();
  }

  return (
    <div className="page-stack logs-page">
      <section className="toolbar-row">
        <div>
          <p className="eyebrow">Observability</p>
          <h2>日志与任务排障</h2>
        </div>
        <button onClick={() => void refresh()} type="button">
          刷新
        </button>
      </section>
      {error ? <div className="error-box">{error}</div> : null}
      <section className="panel">
        <div className="tab-row">
          {TABS.map((item) => (
            <button
              className={tab === item.id ? 'tab-button active' : 'tab-button'}
              key={item.id}
              onClick={() => setTab(item.id)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="filter-grid logs-filter-grid">
          <label>
            request_id
            <input
              onChange={(event) => updateFilter('requestId', event.target.value)}
              value={filters.requestId}
            />
          </label>
          <label>
            run_id
            <input onChange={(event) => updateFilter('runId', event.target.value)} value={filters.runId} />
          </label>
          <label>
            task_run_id
            <input
              onChange={(event) => updateFilter('taskRunId', event.target.value)}
              value={filters.taskRunId}
            />
          </label>
          <label>
            状态 / HTTP
            <input onChange={(event) => updateFilter('status', event.target.value)} value={filters.status} />
          </label>
          <label>
            任务类型 / 动作
            <input onChange={(event) => updateFilter('taskType', event.target.value)} value={filters.taskType} />
          </label>
        </div>
        <div className="button-row">
          <button onClick={() => void refresh()} type="button">
            查询
          </button>
          <button className="secondary-button" onClick={() => setFilters(emptyFilters())} type="button">
            清空
          </button>
          {copied ? <span className="success-text">已复制 {copied}</span> : null}
        </div>
      </section>

      <section className="panel">
        <h3>{TABS.find((item) => item.id === tab)?.label}</h3>
        {currentRows.length === 0 ? <p className="muted">暂无日志</p> : null}
        {tab === 'tasks' ? (
          <TaskRows logs={taskLogs} onCopy={copyRequestId} onDetail={setSelected} onRetry={(log) => void retry(log)} />
        ) : null}
        {tab === 'models' ? <ModelRows logs={modelLogs} onCopy={copyRequestId} onDetail={setSelected} /> : null}
        {tab === 'api' ? <ApiRows logs={apiLogs} onCopy={copyRequestId} onDetail={setSelected} /> : null}
        {tab === 'audit' ? <AuditRows logs={auditLogs} onCopy={copyRequestId} onDetail={setSelected} /> : null}
      </section>

      <LogDetailDrawer onClose={() => setSelected(null)} payload={selected} title="日志详情" />
    </div>
  );
}

function TaskRows({
  logs,
  onCopy,
  onDetail,
  onRetry,
}: {
  logs: TaskRunLog[];
  onCopy: (requestId: string | null) => void;
  onDetail: (payload: unknown) => void;
  onRetry: (log: TaskRunLog) => void;
}) {
  return (
    <div className="observability-list">
      {logs.map((log) => (
        <article className="observability-row" key={log.id}>
          <div>
            <strong>{log.taskType}</strong>
            <p className="muted">{log.resourceType} · {log.resourceId}</p>
          </div>
          <span className={`status-tag status-${log.status.toLowerCase()}`}>{log.status}</span>
          <span>{log.stage || '-'}</span>
          <span>{log.errorCode || '-'}</span>
          <button className="link-button" onClick={() => onCopy(log.requestId)} type="button">
            {log.requestId || '-'}
          </button>
          <div className="button-row">
            <button className="secondary-button" onClick={() => onDetail(log)} type="button">
              详情
            </button>
            {log.retryable ? (
              <button onClick={() => onRetry(log)} type="button">
                重试
              </button>
            ) : null}
          </div>
        </article>
      ))}
    </div>
  );
}

function ModelRows({
  logs,
  onCopy,
  onDetail,
}: {
  logs: ModelCallLog[];
  onCopy: (requestId: string | null) => void;
  onDetail: (payload: unknown) => void;
}) {
  return (
    <div className="observability-list">
      {logs.map((log) => (
        <article className="observability-row" key={log.id}>
          <div>
            <strong>{log.providerName || 'Unknown Provider'}</strong>
            <p className="muted">{log.modelName || '-'} · {log.capability}</p>
          </div>
          <span className={`status-tag status-${log.status.toLowerCase()}`}>{log.status}</span>
          <span>{log.latencyMs ?? 0}ms</span>
          <span>{log.errorCode || '-'}</span>
          <button className="link-button" onClick={() => onCopy(log.requestId)} type="button">
            {log.requestId || '-'}
          </button>
          <button className="secondary-button" onClick={() => onDetail(log)} type="button">
            详情
          </button>
        </article>
      ))}
    </div>
  );
}

function ApiRows({
  logs,
  onCopy,
  onDetail,
}: {
  logs: ApiCallLog[];
  onCopy: (requestId: string | null) => void;
  onDetail: (payload: unknown) => void;
}) {
  return (
    <div className="observability-list">
      {logs.map((log) => (
        <article className="observability-row" key={log.id}>
          <div>
            <strong>{log.method} {log.path}</strong>
            <p className="muted">{log.keyPrefix || '-'}</p>
          </div>
          <span className={`status-tag status-${log.statusCode >= 400 ? 'failed' : 'ready'}`}>{log.statusCode}</span>
          <span>{log.latencyMs}ms</span>
          <span>{log.errorCode || '-'}</span>
          <button className="link-button" onClick={() => onCopy(log.requestId)} type="button">
            {log.requestId || '-'}
          </button>
          <button className="secondary-button" onClick={() => onDetail(log)} type="button">
            详情
          </button>
        </article>
      ))}
    </div>
  );
}

function AuditRows({
  logs,
  onCopy,
  onDetail,
}: {
  logs: AuditLog[];
  onCopy: (requestId: string | null) => void;
  onDetail: (payload: unknown) => void;
}) {
  return (
    <div className="observability-list">
      {logs.map((log) => (
        <article className="observability-row" key={log.id}>
          <div>
            <strong>{log.action}</strong>
            <p className="muted">{log.resourceType} · {log.resourceId || '-'}</p>
          </div>
          <span>{log.actorId || '-'}</span>
          <span>{new Date(log.createdAt).toLocaleString()}</span>
          <span>-</span>
          <button className="link-button" onClick={() => onCopy(log.requestId)} type="button">
            {log.requestId || '-'}
          </button>
          <button className="secondary-button" onClick={() => onDetail(log)} type="button">
            详情
          </button>
        </article>
      ))}
    </div>
  );
}

function initialFilters(): LogFilters {
  const params = new URLSearchParams(window.location.hash.split('?')[1] || '');
  return {
    ...emptyFilters(),
    requestId: params.get('requestId') || '',
    runId: params.get('runId') || '',
    taskRunId: params.get('taskRunId') || '',
  };
}

function emptyFilters(): LogFilters {
  return {
    requestId: '',
    runId: '',
    taskRunId: '',
    status: '',
    taskType: '',
    page: 1,
    pageSize: 20,
  };
}

