import { FormEvent, useEffect, useState } from 'react';

import {
  ConnectionTestResult,
  ModelConfig,
  ModelProvider,
  createModelConfig,
  createModelProvider,
  listModelConfigs,
  listModelProviders,
  setDefaultModelConfig,
  testModelProvider,
} from '../api/modelConfigApi';

export function ModelConfigPage() {
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [configs, setConfigs] = useState<ModelConfig[]>([]);
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

  async function refresh() {
    const [providerResult, configResult] = await Promise.all([
      listModelProviders(),
      listModelConfigs(),
    ]);
    setProviders(providerResult.data);
    setConfigs(configResult.data);
    setSelectedProviderId((current) => current || providerResult.data[0]?.id || '');
  }

  useEffect(() => {
    refresh().catch(() => setNotice('模型配置加载失败。'));
  }, []);

  async function submitProvider(event: FormEvent) {
    event.preventDefault();
    setNotice(null);
    const provider = await createModelProvider({
      providerType,
      name: providerName,
      baseUrl,
      apiKey,
      status: 'ACTIVE',
    });
    setApiKey('');
    setSelectedProviderId(provider.id);
    await refresh();
    setNotice('模型供应商已保存。');
  }

  async function submitModel(event: FormEvent) {
    event.preventDefault();
    if (!selectedProviderId) {
      setNotice('请先创建或选择供应商。');
      return;
    }
    await createModelConfig({
      providerId: selectedProviderId,
      capability,
      modelName,
      isDefault: makeDefault,
    });
    await refresh();
    setNotice('模型实例已保存。');
  }

  async function runConnectionTest(providerId: string) {
    setConnectionResult(null);
    const result = await testModelProvider(providerId);
    setConnectionResult(result);
  }

  async function setDefault(configId: string) {
    await setDefaultModelConfig(configId);
    await refresh();
  }

  return (
    <div className="page-stack">
      <section className="toolbar-row">
        <div>
          <p className="eyebrow">模型配置</p>
          <h2>供应商与模型实例</h2>
        </div>
        {notice ? <span className="status-pill">{notice}</span> : null}
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

      <section className="panel">
        <h3>供应商列表</h3>
        <div className="table-list">
          {providers.map((provider) => (
            <div className="table-row" key={provider.id}>
              <strong>{provider.name}</strong>
              <span>{provider.providerType}</span>
              <span>{provider.secretConfigured ? 'Secret 已配置' : '未配置 Secret'}</span>
              <span>{provider.status}</span>
              <button type="button" onClick={() => runConnectionTest(provider.id)}>
                测试连接
              </button>
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

      <section className="panel">
        <h3>模型实例</h3>
        <div className="table-list">
          {configs.map((item) => (
            <div className="table-row" key={item.id}>
              <strong>{item.modelName}</strong>
              <span>{item.capability}</span>
              <span>{item.isDefault ? '默认' : '非默认'}</span>
              <span>{item.status}</span>
              <button type="button" onClick={() => setDefault(item.id)}>
                设为默认
              </button>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
