import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FormEvent, useEffect, useState } from 'react';

import { errorMessage } from '../../../api/client';
import { queryKeys } from '../../../api/queryClient';
import { EditIcon, TrashIcon } from '../../../shared/ManagementListIcons';
import {
  ConnectionTestResult,
  ModelConfig,
  ModelConfigUpdatePayload,
  ModelProvider,
  ModelProviderUpdatePayload,
  createModelConfig,
  createModelProvider,
  deleteModelConfig,
  deleteModelProvider,
  listModelConfigs,
  listModelProviders,
  setDefaultModelConfig,
  testModelProvider,
  updateModelConfig,
  updateModelProvider,
} from '../api/modelConfigApi';
import { ModelConfigEditModal } from '../components/ModelConfigEditModal';
import { ProviderEditModal } from '../components/ProviderEditModal';

export function ModelConfigPage() {
  const queryClient = useQueryClient();
  const providersQuery = useQuery({
    queryKey: queryKeys.modelProviders(),
    queryFn: () => listModelProviders(),
  });
  const configsQuery = useQuery({
    queryKey: queryKeys.modelConfigs(),
    queryFn: () => listModelConfigs(),
  });

  const providers = providersQuery.data?.data ?? [];
  const configs = configsQuery.data?.data ?? [];

  const [providerName, setProviderName] = useState('DeepSeek Gateway');
  const [providerType, setProviderType] = useState('OPENAI_COMPATIBLE');
  const [baseUrl, setBaseUrl] = useState('mock://success');
  const [apiKey, setApiKey] = useState('');
  const [modelName, setModelName] = useState('knowledge-chat');
  const [capability, setCapability] = useState('CHAT');
  const [selectedProviderId, setSelectedProviderId] = useState('');
  const [makeDefault, setMakeDefault] = useState(true);
  const [connectionResult, setConnectionResult] = useState<ConnectionTestResult | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editingProvider, setEditingProvider] = useState<ModelProvider | null>(null);
  const [editingConfig, setEditingConfig] = useState<ModelConfig | null>(null);

  // Default the selected provider to the first one once loaded.
  useEffect(() => {
    setSelectedProviderId((current) => current || providers[0]?.id || '');
  }, [providers]);

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.modelProviders() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.modelConfigs() });
  }

  const createProviderMutation = useMutation({
    mutationFn: () =>
      createModelProvider({ providerType, name: providerName, baseUrl, apiKey, status: 'ACTIVE' }),
    onSuccess: (provider) => {
      setApiKey('');
      setSelectedProviderId(provider.id);
      invalidate();
      setNotice('模型供应商已保存。');
    },
    onError: (err) => setNotice(errorMessage(err, '供应商保存失败。')),
  });

  const createModelMutation = useMutation({
    mutationFn: () =>
      createModelConfig({
        providerId: selectedProviderId,
        capability,
        modelName,
        isDefault: makeDefault,
      }),
    onSuccess: () => {
      invalidate();
      setNotice('模型实例已保存。');
    },
    onError: (err) => setNotice(errorMessage(err, '模型实例保存失败。')),
  });

  const testMutation = useMutation({
    mutationFn: (providerId: string) => testModelProvider(providerId),
    onSuccess: (result) => setConnectionResult(result),
    onError: (err) => setNotice(errorMessage(err, '连接测试失败。')),
  });

  const setDefaultMutation = useMutation({
    mutationFn: (configId: string) => setDefaultModelConfig(configId),
    onSuccess: invalidate,
    onError: (err) => setNotice(errorMessage(err, '设置默认失败。')),
  });

  const updateProviderMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: ModelProviderUpdatePayload }) =>
      updateModelProvider(id, payload),
    onSuccess: () => {
      invalidate();
      setNotice('供应商已更新。');
    },
  });

  const deleteProviderMutation = useMutation({
    mutationFn: (providerId: string) => deleteModelProvider(providerId),
    onSuccess: (_result, providerId) => {
      // A deleted provider must not stay selected in the create-model form.
      setSelectedProviderId((current) => (current === providerId ? '' : current));
      invalidate();
      setNotice('供应商已删除。');
    },
    onError: (err) => setNotice(errorMessage(err, '供应商删除失败。')),
  });

  const updateConfigMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: ModelConfigUpdatePayload }) =>
      updateModelConfig(id, payload),
    onSuccess: () => {
      invalidate();
      setNotice('模型实例已更新。');
    },
  });

  const deleteConfigMutation = useMutation({
    mutationFn: (configId: string) => deleteModelConfig(configId),
    onSuccess: () => {
      invalidate();
      setNotice('模型实例已删除。');
    },
    onError: (err) => setNotice(errorMessage(err, '模型实例删除失败。')),
  });

  function submitProvider(event: FormEvent) {
    event.preventDefault();
    setNotice(null);
    createProviderMutation.mutate();
  }

  function submitModel(event: FormEvent) {
    event.preventDefault();
    if (!selectedProviderId) {
      setNotice('请先创建或选择供应商。');
      return;
    }
    setNotice(null);
    createModelMutation.mutate();
  }

  function runConnectionTest(providerId: string) {
    setConnectionResult(null);
    testMutation.mutate(providerId);
  }

  function setDefault(configId: string) {
    setDefaultMutation.mutate(configId);
  }

  function removeProvider(provider: ModelProvider) {
    if (window.confirm(`确认删除供应商「${provider.name}」？`)) {
      setNotice(null);
      deleteProviderMutation.mutate(provider.id);
    }
  }

  function removeConfig(config: ModelConfig) {
    const defaultHint = config.isDefault ? '（当前为默认模型，删除后该能力将没有默认模型）' : '';
    if (window.confirm(`确认删除模型实例「${config.modelName}」？${defaultHint}`)) {
      setNotice(null);
      deleteConfigMutation.mutate(config.id);
    }
  }

  const loadFailed = providersQuery.isError || configsQuery.isError;

  return (
    <div className="page-stack">
      <section className="toolbar-row">
        <div>
          <p className="eyebrow">模型配置</p>
          <h2>供应商与模型实例</h2>
        </div>
        {notice ? <span className="status-pill">{notice}</span> : null}
        {loadFailed && !notice ? <span className="status-pill">模型配置加载失败。</span> : null}
      </section>

      <section className="two-column">
        <form className="panel" onSubmit={submitProvider}>
          <h3>新增供应商</h3>
          <label>
            类型
            <select value={providerType} onChange={(event) => setProviderType(event.target.value)}>
              <option value="OPENAI_COMPATIBLE">OpenAI Compatible</option>
              <option value="CLAUDE">Claude</option>
              <option value="OLLAMA">Ollama</option>
              <option value="INTERNAL_GATEWAY">Internal Gateway</option>
            </select>
          </label>
          <label>
            名称
            <input value={providerName} onChange={(event) => setProviderName(event.target.value)} />
          </label>
          <label>
            Base URL
            <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
          </label>
          <label>
            API Key
            <input
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              type="password"
              placeholder="保存后不会回显"
            />
          </label>
          <button type="submit">保存供应商</button>
        </form>

        <form className="panel" onSubmit={submitModel}>
          <h3>新增模型实例</h3>
          <label>
            供应商
            <select
              value={selectedProviderId}
              onChange={(event) => setSelectedProviderId(event.target.value)}
            >
              <option value="">选择供应商</option>
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            能力
            <select value={capability} onChange={(event) => setCapability(event.target.value)}>
              <option value="CHAT">Chat</option>
              <option value="EMBEDDING">Embedding</option>
              <option value="QA_SPLIT">QA Split</option>
            </select>
          </label>
          <label>
            模型名
            <input value={modelName} onChange={(event) => setModelName(event.target.value)} />
          </label>
          <label className="checkbox-row">
            <input
              checked={makeDefault}
              onChange={(event) => setMakeDefault(event.target.checked)}
              type="checkbox"
            />
            设为默认模型
          </label>
          <button type="submit">保存模型</button>
        </form>
      </section>

      <section className="panel management-list-panel">
        <div className="management-list-heading">
          <h3>供应商列表</h3>
        </div>
        <div aria-label="供应商列表" className="management-list model-provider-list" role="table">
          <div className="management-list-head" role="row">
            <span role="columnheader">供应商名称</span>
            <span role="columnheader">类型</span>
            <span role="columnheader">Secret 配置</span>
            <span role="columnheader">状态</span>
            <span role="columnheader">操作</span>
          </div>
          {providers.length === 0 ? <p className="management-list-empty">暂无供应商</p> : null}
          {providers.map((provider) => (
            <div className="management-list-row" key={provider.id} role="row">
              <div className="management-list-primary" role="cell">
                <strong>{provider.name}</strong>
              </div>
              <span className="management-list-cell" role="cell">
                {provider.providerType}
              </span>
              <span className="management-list-cell" role="cell">
                {provider.secretConfigured ? 'Secret 已配置' : '未配置 Secret'}
              </span>
              <span className={`status-tag status-${provider.status.toLowerCase()}`} role="cell">
                {provider.status}
              </span>
              <div className="management-list-actions management-list-actions-wide" role="cell">
                <button
                  className="management-list-action"
                  type="button"
                  onClick={() => runConnectionTest(provider.id)}
                >
                  测试连接
                </button>
                <button
                  className="management-list-action"
                  type="button"
                  onClick={() => setEditingProvider(provider)}
                >
                  <EditIcon />
                  编辑
                </button>
                <button
                  className="management-list-action danger"
                  type="button"
                  onClick={() => removeProvider(provider)}
                >
                  <TrashIcon />
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
        {connectionResult ? (
          <p className={connectionResult.success ? 'success-text' : 'error'}>
            {connectionResult.status} · {connectionResult.latencyMs}ms
            {connectionResult.errorMessage ? ` · ${connectionResult.errorMessage}` : ''}
          </p>
        ) : null}
      </section>

      <section className="panel management-list-panel">
        <div className="management-list-heading">
          <h3>模型实例</h3>
        </div>
        <div aria-label="模型实例" className="management-list model-config-list" role="table">
          <div className="management-list-head" role="row">
            <span role="columnheader">模型名称</span>
            <span role="columnheader">能力</span>
            <span role="columnheader">默认标识</span>
            <span role="columnheader">状态</span>
            <span role="columnheader">操作</span>
          </div>
          {configs.length === 0 ? <p className="management-list-empty">暂无模型实例</p> : null}
          {configs.map((item) => (
            <div className="management-list-row" key={item.id} role="row">
              <div className="management-list-primary" role="cell">
                <strong>{item.modelName}</strong>
              </div>
              <span className="management-list-cell" role="cell">
                {item.capability}
              </span>
              <span className="management-list-cell" role="cell">
                {item.isDefault ? '默认' : '非默认'}
              </span>
              <span className={`status-tag status-${item.status.toLowerCase()}`} role="cell">
                {item.status}
              </span>
              <div className="management-list-actions management-list-actions-wide" role="cell">
                <button
                  className="management-list-action"
                  disabled={item.isDefault}
                  type="button"
                  onClick={() => setDefault(item.id)}
                >
                  设为默认
                </button>
                <button
                  className="management-list-action"
                  type="button"
                  onClick={() => setEditingConfig(item)}
                >
                  <EditIcon />
                  编辑
                </button>
                <button
                  className="management-list-action danger"
                  type="button"
                  onClick={() => removeConfig(item)}
                >
                  <TrashIcon />
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {editingProvider ? (
        <ProviderEditModal
          onClose={() => setEditingProvider(null)}
          onSubmit={(id, payload) =>
            updateProviderMutation.mutateAsync({ id, payload }).then(() => undefined)
          }
          provider={editingProvider}
        />
      ) : null}
      {editingConfig ? (
        <ModelConfigEditModal
          config={editingConfig}
          onClose={() => setEditingConfig(null)}
          onSubmit={(id, payload) =>
            updateConfigMutation.mutateAsync({ id, payload }).then(() => undefined)
          }
        />
      ) : null}
    </div>
  );
}
