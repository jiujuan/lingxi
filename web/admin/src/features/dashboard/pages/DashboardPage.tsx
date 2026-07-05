import { useEffect, useState } from 'react';

import { getDashboardSummary } from '../api/dashboardApi';
import type { DashboardSummary } from '../types';

export function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [days, setDays] = useState(7);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void refresh();
  }, [days]);

  async function refresh() {
    try {
      setSummary(await getDashboardSummary(days));
      setError(null);
    } catch {
      setError('Dashboard 加载失败');
    }
  }

  return (
    <div className="page-stack dashboard-page">
      <section className="toolbar-row">
        <div>
          <p className="eyebrow">Dashboard</p>
          <h2>系统总览</h2>
        </div>
        <div className="button-row">
          <select aria-label="时间范围" onChange={(event) => setDays(Number(event.target.value))} value={days}>
            <option value={7}>近 7 天</option>
            <option value={30}>近 30 天</option>
            <option value={0}>全部</option>
          </select>
          <button onClick={() => void refresh()} type="button">
            刷新
          </button>
        </div>
      </section>
      {error ? <div className="error-box">{error}</div> : null}
      {!summary ? <p className="muted">正在加载指标...</p> : null}
      {summary ? (
        <>
          <section className="metric-grid dashboard-metrics">
            <MetricCard href="#knowledge" label="文档数" value={summary.metrics.documentCount} />
            <MetricCard href="#knowledge" label="QA 对数" value={summary.metrics.qaPairCount} />
            <MetricCard href="#logs?status=FAILED" label="任务失败率" value={`${summary.metrics.taskFailureRate}%`} />
            <MetricCard href="#logs" label="API 调用量" value={summary.metrics.apiCallCount} />
          </section>

          <section className="two-column">
            <div className="panel">
              <h3>文档入库健康</h3>
              <div className="health-grid">
                <div>
                  <span className="field-label">成功率</span>
                  <strong>{summary.ingestionHealth.successRate}%</strong>
                </div>
                <div>
                  <span className="field-label">失败率</span>
                  <strong>{summary.ingestionHealth.failureRate}%</strong>
                </div>
              </div>
              <div className="trend-list">
                {summary.ingestionHealth.stages.length === 0 ? <p className="muted">暂无入库任务</p> : null}
                {summary.ingestionHealth.stages.map((stage) => (
                  <div className="trend-row" key={stage.stage}>
                    <span>{stage.stage}</span>
                    <div className="progress-bar">
                      <i style={{ width: `${percent(stage.successCount, stage.totalCount)}%` }} />
                    </div>
                    <code>{stage.successCount}/{stage.totalCount}</code>
                  </div>
                ))}
              </div>
            </div>
            <div className="panel">
              <h3>问答健康</h3>
              <div className="detail-grid compact-detail">
                <div>
                  <span className="field-label">问答次数</span>
                  <strong>{summary.qaHealth.queryCount}</strong>
                </div>
                <div>
                  <span className="field-label">引用覆盖</span>
                  <strong>{summary.qaHealth.citationCoverageRate}%</strong>
                </div>
                <div>
                  <span className="field-label">拒答率</span>
                  <strong>{summary.qaHealth.refusalRate}%</strong>
                </div>
              </div>
              <div className="detail-grid compact-detail">
                <div>
                  <span className="field-label">命中率</span>
                  <strong>{summary.qaHealth.hitRate}%</strong>
                </div>
                <div>
                  <span className="field-label">首字响应</span>
                  <strong>{summary.qaHealth.firstTokenLatencyMs}ms</strong>
                </div>
              </div>
            </div>
          </section>

          <section className="two-column">
            <div className="panel">
              <h3>最近任务</h3>
              <div className="dashboard-list">
                {summary.recentTasks.length === 0 ? <p className="muted">暂无任务</p> : null}
                {summary.recentTasks.map((task) => (
                  <a className="dashboard-row" href={task.requestId ? `#logs?requestId=${task.requestId}` : '#logs'} key={task.id}>
                    <strong>{task.taskType}</strong>
                    <span className={`status-tag status-${task.status.toLowerCase()}`}>{task.status}</span>
                    <span>{task.stage || '-'}</span>
                  </a>
                ))}
              </div>
            </div>
            <div className="panel">
              <h3>风险事件</h3>
              <div className="dashboard-list">
                {summary.riskEvents.length === 0 ? <p className="muted">暂无风险事件</p> : null}
                {summary.riskEvents.map((event) => (
                  <a
                    className="dashboard-row"
                    href={event.requestId ? `#logs?requestId=${event.requestId}` : '#logs'}
                    key={`${event.type}-${event.createdAt}-${event.message}`}
                  >
                    <strong>{event.type}</strong>
                    <span className={`status-tag ${event.severity === 'HIGH' ? 'status-failed' : 'status-uploaded'}`}>
                      {event.severity}
                    </span>
                    <span>{event.message}</span>
                  </a>
                ))}
              </div>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

function MetricCard({ href, label, value }: { href: string; label: string; value: number | string }) {
  return (
    <a className="metric dashboard-metric-link" href={href}>
      <span>{label}</span>
      <strong>{value}</strong>
    </a>
  );
}

function percent(value: number, total: number) {
  return total ? Math.round((value / total) * 100) : 0;
}

