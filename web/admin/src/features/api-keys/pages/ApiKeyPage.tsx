import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { errorMessage } from '../../../api/client';
import { queryKeys } from '../../../api/queryClient';
import {
  createApiKey,
  disableApiKey,
  listApiCallLogs,
  listApiKeys,
  rotateApiKey,
} from '../api/apiKeyApi';
import { ApiCallLogTable } from '../components/ApiCallLogTable';
import { ApiKeyCreateModal } from '../components/ApiKeyCreateModal';
import type { ApiKey, ApiKeyCreatePayload, ApiKeyCreateResult } from '../types';

export function ApiKeyPage() {
  const queryClient = useQueryClient();
  const keysQuery = useQuery({ queryKey: queryKeys.apiKeys(), queryFn: listApiKeys });
  const logsQuery = useQuery({ queryKey: queryKeys.apiCallLogs(), queryFn: listApiCallLogs });
  const [showCreate, setShowCreate] = useState(false);
  const [oneTimeKey, setOneTimeKey] = useState<ApiKeyCreateResult | null>(null);

  const apiKeys = keysQuery.data?.data ?? [];
  const logs = logsQuery.data?.data ?? [];
  const loadError = keysQuery.error ?? logsQuery.error;

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.apiCallLogs() });
  }

  const createMutation = useMutation({
    mutationFn: (payload: ApiKeyCreatePayload) => createApiKey(payload),
    onSuccess: (created) => {
      setOneTimeKey(created);
      invalidate();
    },
  });
  const disableMutation = useMutation({
    mutationFn: (keyId: string) => disableApiKey(keyId),
    onSuccess: invalidate,
  });
  const rotateMutation = useMutation({
    mutationFn: (keyId: string) => rotateApiKey(keyId),
    onSuccess: (result) => {
      setOneTimeKey(result);
      setShowCreate(true);
      invalidate();
    },
  });

  async function createKey(payload: ApiKeyCreatePayload) {
    await createMutation.mutateAsync(payload);
  }

  function disableKey(key: ApiKey) {
    if (window.confirm(`确认禁用 ${key.name}？`)) {
      disableMutation.mutate(key.id);
    }
  }

  function rotateKey(key: ApiKey) {
    if (window.confirm(`确认轮换 ${key.name}？旧 Key 会立即失效。`)) {
      rotateMutation.mutate(key.id);
    }
  }

  const actionError = disableMutation.error ?? rotateMutation.error;

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
      {keysQuery.isError || logsQuery.isError ? (
        <div className="error-box">{errorMessage(loadError, 'API Key 数据加载失败')}</div>
      ) : null}
      {actionError ? (
        <div className="error-box">{errorMessage(actionError, '操作失败')}</div>
      ) : null}
      <section className="panel">
        <h3>Key 列表</h3>
        <div className="api-key-list">
          {apiKeys.length === 0 ? <p className="muted">暂无 API Key</p> : null}
          {apiKeys.map((key) => (
            <article className="api-key-row" key={key.id}>
              <div>
                <strong>{key.name}</strong>
                <p className="muted">
                  {key.keyPrefix} · {key.scopes.join(', ') || '无 scope'}
                </p>
              </div>
              <span className={`status-tag status-${key.status.toLowerCase()}`}>{key.status}</span>
              <span>{key.rateLimitPerMinute}/min</span>
              <div className="button-row">
                <button className="secondary-button" onClick={() => rotateKey(key)} type="button">
                  轮换
                </button>
                <button className="danger-button" onClick={() => disableKey(key)} type="button">
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
          <a className="secondary-link" href="#logs">
            查看统一日志
          </a>
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
