import { FormEvent, useState } from 'react';

import { errorMessage } from '../../../api/client';
import type { ModelProvider } from '../api/modelConfigApi';
import { modelCapabilityOptions, modelTypeOptions } from '../modelOptions';

export type CreateModelPayload = {
  providerId: string;
  capability: string;
  modelName: string;
  isDefault: boolean;
  config: Record<string, string>;
};

type Props = {
  provider: ModelProvider;
  onClose: () => void;
  onSubmit: (payload: CreateModelPayload) => Promise<void>;
};

export function CreateModelModal({ provider, onClose, onSubmit }: Props) {
  const [displayName, setDisplayName] = useState('');
  const [modelName, setModelName] = useState('');
  const [modelType, setModelType] = useState('CHAT');
  const [capability, setCapability] = useState('CHAT');
  const [isDefault, setIsDefault] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSubmit({
        providerId: provider.id,
        capability,
        modelName,
        isDefault,
        config: { displayName, modelType },
      });
      onClose();
    } catch (err) {
      setError(errorMessage(err, '模型保存失败。'));
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
        aria-label={`添加模型 · ${provider.name}`}
        className="modal-panel model-config-modal"
        onMouseDown={(event) => event.stopPropagation()}
        role="dialog"
      >
        <div className="model-config-modal-title">
          <h3>
            添加模型 <span>· {provider.name}</span>
          </h3>
          <button aria-label="关闭" className="model-config-close" onClick={onClose} type="button">
            ×
          </button>
        </div>
        {error ? <div className="error-box">{error}</div> : null}
        <form className="model-config-form" onSubmit={submit}>
          <label>
            <span className="model-config-field-label">模型名称 <em>*</em></span>
            <input
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="如：DeepSeek V4 Ultra"
              required
              value={displayName}
            />
          </label>
          <label>
            <span className="model-config-field-label">模型 ID <em>*</em></span>
            <input
              onChange={(event) => setModelName(event.target.value)}
              placeholder="如：deepseek-v4-ultra"
              required
              value={modelName}
            />
          </label>
          <label>
            模型类型
            <select onChange={(event) => setModelType(event.target.value)} value={modelType}>
              {modelTypeOptions.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            能力
            <select onChange={(event) => setCapability(event.target.value)} value={capability}>
              {modelCapabilityOptions.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="checkbox-row model-config-default-option">
            <input
              checked={isDefault}
              onChange={(event) => setIsDefault(event.target.checked)}
              type="checkbox"
            />
            设为该能力的默认模型
          </label>
          <div className="model-config-modal-actions">
            <button className="secondary-button" onClick={onClose} type="button">
              取消
            </button>
            <button disabled={saving} type="submit">
              {saving ? '添加中…' : '确认添加'}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
