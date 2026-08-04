import { FormEvent, useState } from 'react';

import { errorMessage } from '../../../api/client';
import type { ModelProvider } from '../api/modelConfigApi';
import { modelCapabilityOptions, modelTypeOptions } from '../modelOptions';

export type CreateModelPayload = {
  providerId: string;
  capability: string;
  modelName: string;
  isDefault: boolean;
  maxTokens?: number;
  timeoutMs: number;
  connectTimeoutMs: number;
  writeTimeoutMs: number;
  readIdleTimeoutMs: number;
  overallTimeoutMs: number;
  config: Record<string, unknown>;
};

type Props = {
  provider: ModelProvider;
  onClose: () => void;
  onSubmit: (payload: CreateModelPayload) => Promise<void>;
};

function timeoutDefaults(providerType: string) {
  if (providerType === 'OLLAMA') {
    return {
      connectTimeoutMs: 5000,
      writeTimeoutMs: 30000,
      readIdleTimeoutMs: 180000,
      overallTimeoutMs: 240000,
    };
  }
  return {
    connectTimeoutMs: 10000,
    writeTimeoutMs: 30000,
    readIdleTimeoutMs: 120000,
    overallTimeoutMs: 180000,
  };
}

export function CreateModelModal({ provider, onClose, onSubmit }: Props) {
  const defaults = timeoutDefaults(provider.providerType);
  const [displayName, setDisplayName] = useState('');
  const [modelName, setModelName] = useState('');
  const [modelType, setModelType] = useState('CHAT');
  const [capability, setCapability] = useState('CHAT');
  const [maxTokens, setMaxTokens] = useState('4096');
  const [connectTimeoutMs, setConnectTimeoutMs] = useState(defaults.connectTimeoutMs);
  const [writeTimeoutMs, setWriteTimeoutMs] = useState(defaults.writeTimeoutMs);
  const [readIdleTimeoutMs, setReadIdleTimeoutMs] = useState(defaults.readIdleTimeoutMs);
  const [overallTimeoutMs, setOverallTimeoutMs] = useState(defaults.overallTimeoutMs);
  const [maxInputTokens, setMaxInputTokens] = useState('4096');
  const [reservedOutputTokens, setReservedOutputTokens] = useState('2048');
  const [maxRetries, setMaxRetries] = useState('1');
  const [maxSplitDepth, setMaxSplitDepth] = useState('1');
  const [isDefault, setIsDefault] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (overallTimeoutMs < readIdleTimeoutMs) {
      setError('单次调用总超时不能小于首 Token/读取空闲超时。');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const config: Record<string, unknown> = { displayName, modelType };
      if (capability === 'QA_SPLIT') {
        config.qaSplit = {
          maxInputTokens: Number(maxInputTokens),
          reservedOutputTokens: Number(reservedOutputTokens),
          maxRetries: Number(maxRetries),
          maxSplitDepth: Number(maxSplitDepth),
        };
      }
      await onSubmit({
        providerId: provider.id,
        capability,
        modelName,
        isDefault,
        maxTokens: maxTokens ? Number(maxTokens) : undefined,
        timeoutMs: overallTimeoutMs,
        connectTimeoutMs,
        writeTimeoutMs,
        readIdleTimeoutMs,
        overallTimeoutMs,
        config,
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
          <label>
            最大输出 Tokens
            <input
              min={1}
              onChange={(event) => setMaxTokens(event.target.value)}
              type="number"
              value={maxTokens}
            />
          </label>
          <label>
            连接超时（毫秒）
            <input
              min={100}
              onChange={(event) => setConnectTimeoutMs(Number(event.target.value))}
              type="number"
              value={connectTimeoutMs}
            />
          </label>
          <label>
            请求写入超时（毫秒）
            <input
              min={100}
              onChange={(event) => setWriteTimeoutMs(Number(event.target.value))}
              type="number"
              value={writeTimeoutMs}
            />
          </label>
          <label>
            首 Token/读取空闲超时（毫秒）
            <input
              min={100}
              onChange={(event) => setReadIdleTimeoutMs(Number(event.target.value))}
              type="number"
              value={readIdleTimeoutMs}
            />
          </label>
          <label>
            单次调用总超时（毫秒）
            <input
              min={100}
              onChange={(event) => setOverallTimeoutMs(Number(event.target.value))}
              type="number"
              value={overallTimeoutMs}
            />
          </label>
          {capability === 'QA_SPLIT' ? (
            <>
              <label>
                QA 最大输入 Tokens
                <input
                  min={1}
                  onChange={(event) => setMaxInputTokens(event.target.value)}
                  type="number"
                  value={maxInputTokens}
                />
              </label>
              <label>
                QA 输出预留 Tokens
                <input
                  min={1}
                  onChange={(event) => setReservedOutputTokens(event.target.value)}
                  type="number"
                  value={reservedOutputTokens}
                />
              </label>
              <label>
                QA Batch retry 次数
                <input
                  min={0}
                  onChange={(event) => setMaxRetries(event.target.value)}
                  type="number"
                  value={maxRetries}
                />
              </label>
              <label>
                QA 最大二分深度
                <input
                  min={0}
                  onChange={(event) => setMaxSplitDepth(event.target.value)}
                  type="number"
                  value={maxSplitDepth}
                />
              </label>
            </>
          ) : null}
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
