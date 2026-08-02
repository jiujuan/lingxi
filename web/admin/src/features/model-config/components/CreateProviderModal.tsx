import { FormEvent, useState } from 'react';

import { errorMessage } from '../../../api/client';

export type CreateProviderPayload = {
  providerType: string;
  name: string;
  baseUrl: string;
  apiKey: string;
  status: string;
};

type Props = {
  onClose: () => void;
  onSubmit: (payload: CreateProviderPayload) => Promise<void>;
};

export function CreateProviderModal({ onClose, onSubmit }: Props) {
  const [providerType, setProviderType] = useState('OPENAI_COMPATIBLE');
  const [name, setName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSubmit({ providerType, name, baseUrl, apiKey, status: 'ACTIVE' });
      onClose();
    } catch (err) {
      setError(errorMessage(err, '供应商保存失败。'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="modal-backdrop model-config-modal-backdrop"
      onMouseDown={onClose}
      role="presentation"
    >
      <section
        aria-label="增加供应商"
        className="modal-panel model-config-modal"
        onMouseDown={(event) => event.stopPropagation()}
        role="dialog"
      >
        <div className="model-config-modal-title">
          <h3>增加供应商</h3>
          <button aria-label="关闭" className="model-config-close" onClick={onClose} type="button">
            ×
          </button>
        </div>
        {error ? <div className="error-box">{error}</div> : null}
        <form className="model-config-form" onSubmit={submit}>
          <label>
            <span className="model-config-field-label">供应商类型 <em>*</em></span>
            <select onChange={(event) => setProviderType(event.target.value)} value={providerType}>
              <option value="OPENAI_COMPATIBLE">OpenAI 兼容</option>
              <option value="CLAUDE">Anthropic Claude</option>
              <option value="OLLAMA">Ollama</option>
              <option value="INTERNAL_GATEWAY">内部网关</option>
            </select>
          </label>
          <label>
            <span className="model-config-field-label">供应商名称 <em>*</em></span>
            <input
              onChange={(event) => setName(event.target.value)}
              placeholder="如：DeepSeek"
              required
              value={name}
            />
          </label>
          <label>
            API Base URL
            <input
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="https://api.example.com"
              value={baseUrl}
            />
          </label>
          <label>
            API Key
            <input
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="可稍后在编辑供应商中配置"
              type="password"
              value={apiKey}
            />
          </label>
          <div className="model-config-modal-actions">
            <button className="secondary-button" onClick={onClose} type="button">
              取消
            </button>
            <button disabled={saving} type="submit">
              {saving ? '保存中…' : '确认添加'}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
