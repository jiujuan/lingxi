import { useState } from 'react';

import { errorMessage } from '../../../api/client';
import type { ModelProvider, ModelProviderUpdatePayload } from '../api/modelConfigApi';

type Props = {
  provider: ModelProvider;
  onClose: () => void;
  onSubmit: (providerId: string, payload: ModelProviderUpdatePayload) => Promise<void>;
};

export function ProviderEditModal({ provider, onClose, onSubmit }: Props) {
  const [name, setName] = useState(provider.name);
  const [baseUrl, setBaseUrl] = useState(provider.baseUrl ?? '');
  const [apiKey, setApiKey] = useState('');
  const [status, setStatus] = useState(provider.status);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit() {
    setSaving(true);
    setError(null);
    const payload: ModelProviderUpdatePayload = { name, baseUrl, status };
    if (apiKey) {
      payload.apiKey = apiKey;
    }
    try {
      await onSubmit(provider.id, payload);
      onClose();
    } catch (err) {
      setError(errorMessage(err, '保存失败'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section aria-label="编辑供应商" className="modal-panel" role="dialog">
        <div className="toolbar-row compact">
          <h3>编辑供应商</h3>
          <button className="secondary-button" onClick={onClose} type="button">
            关闭
          </button>
        </div>
        <p className="muted">类型：{provider.providerType}（创建后不可修改）</p>
        {error ? <div className="error-box">{error}</div> : null}
        <form
          className="form-grid"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label>
            名称
            <input onChange={(event) => setName(event.target.value)} required value={name} />
          </label>
          <label>
            Base URL
            <input onChange={(event) => setBaseUrl(event.target.value)} value={baseUrl} />
          </label>
          <label>
            API Key
            <input
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={provider.secretConfigured ? '留空则保持原 Key 不变' : '未配置 Secret'}
              type="password"
              value={apiKey}
            />
          </label>
          <label>
            状态
            <select onChange={(event) => setStatus(event.target.value)} value={status}>
              <option value="ACTIVE">启用</option>
              <option value="DISABLED">停用</option>
            </select>
          </label>
          <button disabled={saving} type="submit">
            {saving ? '保存中…' : '保存'}
          </button>
        </form>
      </section>
    </div>
  );
}
