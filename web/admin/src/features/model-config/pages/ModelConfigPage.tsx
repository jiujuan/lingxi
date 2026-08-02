import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';

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
import { CreateModelModal, CreateModelPayload } from '../components/CreateModelModal';
import { modelCapabilityOptions } from '../modelOptions';
import { CreateProviderModal, CreateProviderPayload } from '../components/CreateProviderModal';
import { ModelConfigEditModal } from '../components/ModelConfigEditModal';
import { ProviderEditModal } from '../components/ProviderEditModal';

const capabilityLabels = Object.fromEntries(modelCapabilityOptions) as Record<string, string>;
const providerPalette = ['#346cff', '#7c52f4', '#0daf82', '#ef4b55', '#f08c00', '#1b6cf0'];

function displayName(config: ModelConfig) {
  const configuredName = config.config.displayName;
  return typeof configuredName === 'string' && configuredName.trim()
    ? configuredName
    : config.modelName;
}

function capabilityLabel(capability: string) {
  return capabilityLabels[capability] ?? capability;
}

function providerColor(provider: ModelProvider, index: number) {
  const configuredColor = provider.config.brandColor;
  return typeof configuredColor === 'string'
    ? configuredColor
    : providerPalette[index % providerPalette.length];
}

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

  const providers = useMemo(() => providersQuery.data?.data ?? [], [providersQuery.data]);
  const configs = useMemo(() => configsQuery.data?.data ?? [], [configsQuery.data]);
  const [selectedProviderId, setSelectedProviderId] = useState('');
  const [connectionResult, setConnectionResult] = useState<ConnectionTestResult | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showProviderCreate, setShowProviderCreate] = useState(false);
  const [showModelCreate, setShowModelCreate] = useState(false);
  const [editingProvider, setEditingProvider] = useState<ModelProvider | null>(null);
  const [editingConfig, setEditingConfig] = useState<ModelConfig | null>(null);

  useEffect(() => {
    setSelectedProviderId((current) => {
      if (providers.some((provider) => provider.id === current)) {
        return current;
      }
      return providers[0]?.id ?? '';
    });
  }, [providers]);

  const selectedProvider = providers.find((provider) => provider.id === selectedProviderId) ?? null;
  const selectedProviderModels = useMemo(
    () => configs.filter((config) => config.providerId === selectedProviderId),
    [configs, selectedProviderId],
  );

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.modelProviders() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.modelConfigs() });
  }

  const createProviderMutation = useMutation({
    mutationFn: (payload: CreateProviderPayload) => createModelProvider(payload),
    onSuccess: (provider) => {
      setSelectedProviderId(provider.id);
      invalidate();
      setNotice('模型供应商已保存。');
    },
  });

  const createModelMutation = useMutation({
    mutationFn: (payload: CreateModelPayload) => createModelConfig(payload),
    onSuccess: () => {
      invalidate();
      setNotice('模型已添加。');
    },
  });

  const testMutation = useMutation({
    mutationFn: (providerId: string) => testModelProvider(providerId),
    onSuccess: (result) => setConnectionResult(result),
    onError: (err) => setNotice(errorMessage(err, '连接测试失败。')),
  });

  const setDefaultMutation = useMutation({
    mutationFn: (configId: string) => setDefaultModelConfig(configId),
    onSuccess: () => {
      invalidate();
      setNotice('默认模型已更新。');
    },
    onError: (err) => setNotice(errorMessage(err, '设置默认失败。')),
  });

  const updateProviderMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: ModelProviderUpdatePayload }) =>
      updateModelProvider(id, payload),
    onSuccess: () => {
      invalidate();
      setNotice('供应商已更新。');
    },
    onError: (err) => setNotice(errorMessage(err, '供应商更新失败。')),
  });

  const deleteProviderMutation = useMutation({
    mutationFn: (providerId: string) => deleteModelProvider(providerId),
    onSuccess: (_result, providerId) => {
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
    onError: (err) => setNotice(errorMessage(err, '模型实例更新失败。')),
  });

  const deleteConfigMutation = useMutation({
    mutationFn: (configId: string) => deleteModelConfig(configId),
    onSuccess: () => {
      invalidate();
      setNotice('模型实例已删除。');
    },
    onError: (err) => setNotice(errorMessage(err, '模型实例删除失败。')),
  });

  function removeProvider(provider: ModelProvider) {
    if (window.confirm(`确认删除供应商「${provider.name}」？`)) {
      setNotice(null);
      deleteProviderMutation.mutate(provider.id);
    }
  }

  function removeConfig(config: ModelConfig) {
    const defaultHint = config.isDefault ? '（当前为默认模型，删除后该能力将没有默认模型）' : '';
    if (window.confirm(`确认删除模型实例「${displayName(config)}」？${defaultHint}`)) {
      setNotice(null);
      deleteConfigMutation.mutate(config.id);
    }
  }

  const loadFailed = providersQuery.isError || configsQuery.isError;

  return (
    <div className="page-stack model-config-page">
      <section className="model-config-heading">
        <div>
          <h2>模型配置</h2>
          <p>接入并管理各类模型供应商，为 AI 问答、Embedding 向量化与知识提炼提供模型服务。</p>
        </div>
        {notice ? <span className="status-pill">{notice}</span> : null}
        {loadFailed && !notice ? <span className="status-pill">模型配置加载失败。</span> : null}
      </section>

      <section className="model-config-workspace">
        <aside aria-label="模型提供商" className="model-provider-sidebar">
          <div className="model-provider-sidebar-heading">
            <h3>模型提供商</h3>
            <button
              className="secondary-button model-provider-add-button"
              onClick={() => setShowProviderCreate(true)}
              type="button"
            >
              增加供应商
            </button>
          </div>
          <div className="model-provider-nav">
            {providers.length === 0 ? <p className="model-config-empty">暂未配置供应商</p> : null}
            {providers.map((provider, index) => {
              const isSelected = provider.id === selectedProviderId;
              const isActive = provider.status === 'ACTIVE';
              return (
                <button
                  aria-current={isSelected ? 'page' : undefined}
                  className={`model-provider-option${isSelected ? ' selected' : ''}`}
                  key={provider.id}
                  onClick={() => {
                    setSelectedProviderId(provider.id);
                    setConnectionResult(null);
                  }}
                  type="button"
                >
                  <span
                    className="model-provider-logo"
                    style={{ backgroundColor: providerColor(provider, index) }}
                  >
                    {provider.name.slice(0, 1).toUpperCase()}
                  </span>
                  <span className="model-provider-option-copy">
                    <strong>{provider.name}</strong>
                    <small>{provider.providerType.replaceAll('_', ' ')}</small>
                  </span>
                  <span
                    aria-checked={isActive}
                    aria-label={`${provider.name}${isActive ? '已启用' : '已停用'}`}
                    className={`model-provider-switch${isActive ? ' active' : ''}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      updateProviderMutation.mutate({
                        id: provider.id,
                        payload: { status: isActive ? 'DISABLED' : 'ACTIVE' },
                      });
                    }}
                    role="switch"
                  >
                    <i />
                  </span>
                </button>
              );
            })}
          </div>
        </aside>

        <section className="model-provider-detail">
          {selectedProvider ? (
            <>
              <div className="model-provider-detail-heading">
                <div>
                  <h3>
                    {selectedProvider.name} 提供商设置
                    <button
                      aria-label={`编辑 ${selectedProvider.name}`}
                      className="model-config-inline-edit"
                      onClick={() => setEditingProvider(selectedProvider)}
                      type="button"
                    >
                      ✎
                    </button>
                  </h3>
                  <p>{selectedProvider.status === 'ACTIVE' ? '已启用' : '已停用'}</p>
                </div>
                <button
                  className="secondary-button"
                  disabled={testMutation.isPending}
                  onClick={() => {
                    setConnectionResult(null);
                    testMutation.mutate(selectedProvider.id);
                  }}
                  type="button"
                >
                  {testMutation.isPending ? '测试中…' : '测试连接'}
                </button>
              </div>

              <div className="model-provider-settings">
                <label>
                  API Key
                  <span className="model-config-input-like">
                    {selectedProvider.secretConfigured ? '••••••••••••••••••••••' : '尚未配置'}
                  </span>
                </label>
                <label>
                  API Base URL
                  <span className="model-config-input-like">
                    {selectedProvider.baseUrl || '未配置'}
                  </span>
                </label>
                <label>
                  API 格式
                  <span className="model-provider-protocol">
                    {selectedProvider.providerType === 'CLAUDE' ? 'Anthropic 兼容' : 'OpenAI 兼容'}
                  </span>
                </label>
              </div>
              {connectionResult ? (
                <p className={connectionResult.success ? 'success-text' : 'error'}>
                  {connectionResult.status} · {connectionResult.latencyMs}ms
                  {connectionResult.errorMessage ? ` · ${connectionResult.errorMessage}` : ''}
                </p>
              ) : null}

              <div className="available-models-heading">
                <h3>可用模型列表</h3>
                <button
                  className="model-config-add-model"
                  onClick={() => setShowModelCreate(true)}
                  type="button"
                >
                  + 添加模型
                </button>
              </div>
              <div className="available-model-list">
                {selectedProviderModels.length === 0 ? (
                  <p className="model-config-empty">该供应商暂未添加模型。</p>
                ) : null}
                {selectedProviderModels.map((config) => (
                  <button
                    className="available-model-card"
                    key={config.id}
                    onClick={() => setEditingConfig(config)}
                    title="编辑模型实例"
                    type="button"
                  >
                    <span
                      className={`available-model-status ${config.status === 'ACTIVE' ? 'active' : ''}`}
                    />
                    <span className="available-model-copy">
                      <strong>{displayName(config)}</strong>
                      <small>{config.modelName}</small>
                    </span>
                    <span className="available-model-type">
                      {capabilityLabel(config.capability)}
                    </span>
                  </button>
                ))}
              </div>
              <p className="model-config-tip">
                配置保存后即时生效；AI 问答、向量化与知识提炼任务将按优先级调度可用模型。
              </p>
            </>
          ) : (
            <div className="model-config-empty-state">
              <h3>先添加一个模型供应商</h3>
              <p>配置供应商连接信息后，即可添加和管理该供应商下的模型。</p>
              <button onClick={() => setShowProviderCreate(true)} type="button">
                增加供应商
              </button>
            </div>
          )}
        </section>
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
                  onClick={() => testMutation.mutate(provider.id)}
                  type="button"
                >
                  测试连接
                </button>
                <button
                  className="management-list-action"
                  onClick={() => setEditingProvider(provider)}
                  type="button"
                >
                  <EditIcon />
                  编辑
                </button>
                <button
                  className="management-list-action danger"
                  onClick={() => removeProvider(provider)}
                  type="button"
                >
                  <TrashIcon />
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
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
                <strong>{displayName(item)}</strong>
                {displayName(item) !== item.modelName ? <span>{item.modelName}</span> : null}
              </div>
              <span className="management-list-cell" role="cell">
                {capabilityLabel(item.capability)}
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
                  onClick={() => setDefaultMutation.mutate(item.id)}
                  type="button"
                >
                  设为默认
                </button>
                <button
                  className="management-list-action"
                  onClick={() => setEditingConfig(item)}
                  type="button"
                >
                  <EditIcon />
                  编辑
                </button>
                <button
                  className="management-list-action danger"
                  onClick={() => removeConfig(item)}
                  type="button"
                >
                  <TrashIcon />
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {showProviderCreate ? (
        <CreateProviderModal
          onClose={() => setShowProviderCreate(false)}
          onSubmit={(payload) => createProviderMutation.mutateAsync(payload).then(() => undefined)}
        />
      ) : null}
      {showModelCreate && selectedProvider ? (
        <CreateModelModal
          onClose={() => setShowModelCreate(false)}
          onSubmit={(payload) => createModelMutation.mutateAsync(payload).then(() => undefined)}
          provider={selectedProvider}
        />
      ) : null}
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
