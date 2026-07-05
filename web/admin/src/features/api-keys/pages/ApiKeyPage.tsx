import { useEffect, useState } from 'react';

import {
  createApiKey,
  disableApiKey,
  listApiCallLogs,
  listApiKeys,
  rotateApiKey,
} from '../api/apiKeyApi';
import { ApiCallLogTable } from '../components/ApiCallLogTable';
import { ApiKeyCreateModal } from '../components/ApiKeyCreateModal';
import type { ApiCallLog, ApiKey, ApiKeyCreatePayload, ApiKeyCreateResult } from '../types';

export function ApiKeyPage() {
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [logs, setLogs] = useState<ApiCallLog[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [oneTimeKey, setOneTimeKey] = useState<ApiKeyCreateResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void refresh();
  }, []);

  async function refresh() {
    try {
      const [keysResult, logsResult] = await Promise.all([listApiKeys(), listApiCallLogs()]);
      setApiKeys(keysResult.data);
      setLogs(logsResult.data);
      setError(null);
    } catch {
      setError('API Key 数据加载失败');
    }
  }

  async function createKey(payload: ApiKeyCreatePayload) {
    const created = await createApiKey(payload);
    setOneTimeKey(created);
    await refresh();
  }

  async function disableKey(key: ApiKey) {
    if (!window.confirm(`确认禁用 ${key.name}？`)) {
      return;
    }
    await disableApiKey(key.id);
    await refresh();
  }

  async function rotateKey(key: ApiKey) {
    if (!window.confirm(`确认轮换 ${key.name}？旧 Key 会立即失效。`)) {
      return;
    }
    setOneTimeKey(await rotateApiKey(key.id));
    setShowCreate(true);
    await refresh();
  }

  return (
    <div className="page-stack api-key-page">
      <section className="toolbar-row">
        <div>
          <p className="eyebrow">API Key</p>
          <h2>内部系统访问密钥</h2>
        </div>
        <button
          onClick={() => {
            setOneTimeKey(null);
            setShowCreate(true);
          }}
          type="button"
        >
          创建 Key
        </button>
      </section>
      {error ? <div className="error-box">{error}</div> : null}
      <section className="panel">
        <h3>Key 列表</h3>
        <div className="api-key-list">
          {apiKeys.length === 0 ? <p className="muted">暂无 API Key</p> : null}
          {apiKeys.map((key) => (
            <article className="api-key-row" key={key.id}>
              <div>
                <strong>{key.name}</strong>
                <p className="muted">{key.keyPrefix} · {key.scopes.join(', ') || '无 scope'}</p>
              </div>
              <span className={`status-tag status-${key.status.toLowerCase()}`}>{key.status}</span>
              <span>{key.rateLimitPerMinute}/min</span>
              <div className="button-row">
                <button className="secondary-button" onClick={() => void rotateKey(key)} type="button">
                  轮换
                </button>
                <button className="danger-button" onClick={() => void disableKey(key)} type="button">
                  禁用
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="toolbar-row compact">
          <h3>调用示例</h3>
          <a className="secondary-link" href="#logs">查看统一日志</a>
        </div>
        <pre>{`curl -H "Authorization: Bearer lk_live_****" https://example.com/v1/chat/completions`}</pre>
      </section>
      <ApiCallLogTable logs={logs} />
      {showCreate ? (
        <ApiKeyCreateModal
          createdKey={oneTimeKey}
          onClose={() => {
            setShowCreate(false);
            setOneTimeKey(null);
          }}
          onCreate={createKey}
        />
      ) : null}
    </div>
  );
}
