import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import type { ReactNode } from 'react';

import { errorMessage } from '../../../api/client';
import {
  listApiCallLogs,
  listAuditLogs,
  listModelCallLogs,
  listTaskRunLogs,
  retryTaskRun,
} from '../api/logsApi';
import { LogDetailDrawer } from '../components/LogDetailDrawer';
import { PermissionGate } from '../../../auth/PermissionGate';
import { formatDateTime } from '../../../shared/format';
import type { ApiCallLog, AuditLog, LogFilters, ModelCallLog, TaskRunLog } from '../types';

type Tab = 'tasks' | 'models' | 'api' | 'audit';

const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'tasks', label: '任务日志' },
  { id: 'models', label: '模型调用' },
  { id: 'api', label: 'API 调用' },
  { id: 'audit', label: '审计日志' },
];

export function LogsPage() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>('tasks');
  const [filters, setFilters] = useState<LogFilters>(() => initialFilters());
  const [appliedFilters, setAppliedFilters] = useState<LogFilters>(() => initialFilters());
  const [selected, setSelected] = useState<unknown>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const logsQuery = useQuery({
    queryKey: ['logs', tab, appliedFilters] as const,
    queryFn: () => fetchLogs(tab, appliedFilters),
  });
  const rows = logsQuery.data ?? [];

  const retryMutation = useMutation({
    mutationFn: (log: TaskRunLog) => retryTaskRun(log.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['logs'] }),
  });

  function updateFilter(key: keyof LogFilters, value: string | number) {
    setFilters((current) => ({
      ...current,
      [key]: value,
      page: key === 'page' ? Number(value) : 1,
    }));
  }

  function applyFilters() {
    setAppliedFilters(filters);
  }

  function clearFilters() {
    const cleared = emptyFilters();
    setFilters(cleared);
    setAppliedFilters(cleared);
  }

  async function copyRequestId(requestId: string | null) {
    if (!requestId) return;
    await navigator.clipboard.writeText(requestId);
    setCopied(requestId);
    window.setTimeout(() => setCopied(null), 1200);
  }

  function retry(log: TaskRunLog) {
    if (!window.confirm(`确认重试任务 ${log.taskType}？`)) {
      return;
    }
    retryMutation.mutate(log);
  }

  return (
    <div className="page-stack logs-page">
      <section className="toolbar-row">
        <div>
          <p className="eyebrow">Observability</p>
          <h2>日志与任务排障</h2>
        </div>
        <button onClick={() => void logsQuery.refetch()} type="button">
          刷新
        </button>
      </section>
      {logsQuery.isError ? (
        <div className="error-box">{errorMessage(logsQuery.error, '日志加载失败')}</div>
      ) : null}
      {retryMutation.isError ? (
        <div className="error-box">{errorMessage(retryMutation.error, '任务重试失败')}</div>
      ) : null}
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
            <input
              onChange={(event) => updateFilter('runId', event.target.value)}
              value={filters.runId}
            />
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
            <input
              onChange={(event) => updateFilter('status', event.target.value)}
              value={filters.status}
            />
          </label>
          <label>
            任务类型 / 动作
            <input
              onChange={(event) => updateFilter('taskType', event.target.value)}
              value={filters.taskType}
            />
          </label>
        </div>
        <div className="button-row">
          <button onClick={applyFilters} type="button">
            查询
          </button>
          <button className="secondary-button" onClick={clearFilters} type="button">
            清空
          </button>
          {copied ? <span className="success-text">已复制 {copied}</span> : null}
        </div>
      </section>

      <section className="panel">
        <h3>{TABS.find((item) => item.id === tab)?.label}</h3>
        {rows.length === 0 ? <p className="muted">暂无日志</p> : null}
        {tab === 'tasks' ? (
          <TaskRows
            logs={rows as TaskRunLog[]}
            onCopy={copyRequestId}
            onDetail={setSelected}
            onRetry={retry}
          />
        ) : null}
        {tab === 'models' ? (
          <ModelRows logs={rows as ModelCallLog[]} onCopy={copyRequestId} onDetail={setSelected} />
        ) : null}
        {tab === 'api' ? (
          <ApiRows logs={rows as ApiCallLog[]} onCopy={copyRequestId} onDetail={setSelected} />
        ) : null}
        {tab === 'audit' ? (
          <AuditRows logs={rows as AuditLog[]} onCopy={copyRequestId} onDetail={setSelected} />
        ) : null}
      </section>

      <LogDetailDrawer onClose={() => setSelected(null)} payload={selected} title="日志详情" />
    </div>
  );
}

async function fetchLogs(
  tab: Tab,
  filters: LogFilters,
): Promise<Array<TaskRunLog | ModelCallLog | ApiCallLog | AuditLog>> {
  if (tab === 'tasks') return (await listTaskRunLogs(filters)).data;
  if (tab === 'models') return (await listModelCallLogs(filters)).data;
  if (tab === 'api') return (await listApiCallLogs(filters)).data;
  return (await listAuditLogs(filters)).data;
}

function LogRow({
  primary,
  secondary,
  cells,
  requestId,
  onCopy,
  onDetail,
  action,
}: {
  primary: ReactNode;
  secondary: ReactNode;
  cells: ReactNode;
  requestId: string | null;
  onCopy: (requestId: string | null) => void;
  onDetail: () => void;
  action?: ReactNode;
}) {
  const detail = (
    <button className="secondary-button" onClick={onDetail} type="button">
      详情
    </button>
  );
  return (
    <article className="observability-row">
      <div>
        <strong>{primary}</strong>
        <p className="muted">{secondary}</p>
      </div>
      {cells}
      <button className="link-button" onClick={() => onCopy(requestId)} type="button">
        {requestId || '-'}
      </button>
      {action ? (
        <div className="button-row">
          {detail}
          {action}
        </div>
      ) : (
        detail
      )}
    </article>
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
        <LogRow
          key={log.id}
          primary={log.taskType}
          secondary={`${log.resourceType} · ${log.resourceId}`}
          cells={
            <>
              <span className={`status-tag status-${log.status.toLowerCase()}`}>{log.status}</span>
              <span>{log.stage || '-'}</span>
              <span>{log.errorCode || '-'}</span>
            </>
          }
          requestId={log.requestId}
          onCopy={onCopy}
          onDetail={() => onDetail(log)}
          action={
            log.retryable ? (
              <PermissionGate permission="TASK_RETRY">
                <button onClick={() => onRetry(log)} type="button">
                  重试
                </button>
              </PermissionGate>
            ) : undefined
          }
        />
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
        <LogRow
          key={log.id}
          primary={log.providerName || 'Unknown Provider'}
          secondary={`${log.modelName || '-'} · ${log.capability}`}
          cells={
            <>
              <span className={`status-tag status-${log.status.toLowerCase()}`}>{log.status}</span>
              <span>{log.latencyMs ?? 0}ms</span>
              <span>{log.errorCode || '-'}</span>
            </>
          }
          requestId={log.requestId}
          onCopy={onCopy}
          onDetail={() => onDetail(log)}
        />
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
        <LogRow
          key={log.id}
          primary={`${log.method} ${log.path}`}
          secondary={log.keyPrefix || '-'}
          cells={
            <>
              <span className={`status-tag status-${log.statusCode >= 400 ? 'failed' : 'ready'}`}>
                {log.statusCode}
              </span>
              <span>{log.latencyMs}ms</span>
              <span>{log.errorCode || '-'}</span>
            </>
          }
          requestId={log.requestId}
          onCopy={onCopy}
          onDetail={() => onDetail(log)}
        />
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
        <LogRow
          key={log.id}
          primary={log.action}
          secondary={`${log.resourceType} · ${log.resourceId || '-'}`}
          cells={
            <>
              <span>{log.actorId || '-'}</span>
              <span>{formatDateTime(log.createdAt)}</span>
              <span>-</span>
            </>
          }
          requestId={log.requestId}
          onCopy={onCopy}
          onDetail={() => onDetail(log)}
        />
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
