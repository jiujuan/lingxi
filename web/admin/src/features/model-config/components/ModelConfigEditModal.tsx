import { useState } from 'react';

import { errorMessage } from '../../../api/client';
import type { ModelConfig, ModelConfigUpdatePayload } from '../api/modelConfigApi';

type Props = {
  config: ModelConfig;
  onClose: () => void;
  onSubmit: (configId: string, payload: ModelConfigUpdatePayload) => Promise<void>;
};

export function ModelConfigEditModal({ config, onClose, onSubmit }: Props) {
  const [modelName, setModelName] = useState(config.modelName);
  const [timeoutMs, setTimeoutMs] = useState(config.timeoutMs);
  const [maxTokens, setMaxTokens] = useState(config.maxTokens?.toString() ?? '');
  const [embeddingDimension, setEmbeddingDimension] = useState(
    config.embeddingDimension?.toString() ?? '',
  );
  const [isDefault, setIsDefault] = useState(config.isDefault);
  const [status, setStatus] = useState(config.status);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit() {
    setSaving(true);
    setError(null);
    const payload: ModelConfigUpdatePayload = {
      modelName,
      timeoutMs,
      isDefault,
      status,
    };
    // The PATCH treats missing fields as "unchanged", so only send the
    // optional numbers when a value is filled in.
    if (maxTokens) {
      payload.maxTokens = Number(maxTokens);
    }
    if (embeddingDimension) {
      payload.embeddingDimension = Number(embeddingDimension);
    }
    try {
      await onSubmit(config.id, payload);
      onClose();
    } catch (err) {
      setError(errorMessage(err, '保存失败'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section aria-label="编辑模型实例" className="modal-panel" role="dialog">
        <div className="toolbar-row compact">
          <h3>编辑模型实例</h3>
          <button className="secondary-button" onClick={onClose} type="button">
            关闭
          </button>
        </div>
        <p className="muted">能力：{config.capability}（创建后不可修改）</p>
        {error ? <div className="error-box">{error}</div> : null}
        <form
          className="form-grid"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label>
            模型名
            <input
              onChange={(event) => setModelName(event.target.value)}
              required
              value={modelName}
            />
          </label>
          <label>
            超时（毫秒）
            <input
              min={1000}
              onChange={(event) => setTimeoutMs(Number(event.target.value))}
              type="number"
              value={timeoutMs}
            />
          </label>
          <label>
            最大 Tokens
            <input
              min={1}
              onChange={(event) => setMaxTokens(event.target.value)}
              placeholder="留空不限制"
              type="number"
              value={maxTokens}
            />
          </label>
          {config.capability === 'EMBEDDING' ? (
            <label>
              Embedding 维度
              <input
                min={1}
                onChange={(event) => setEmbeddingDimension(event.target.value)}
                placeholder="如 1024"
                type="number"
                value={embeddingDimension}
              />
            </label>
          ) : null}
          <label>
            状态
            <select onChange={(event) => setStatus(event.target.value)} value={status}>
              <option value="ACTIVE">启用</option>
              <option value="DISABLED">停用</option>
            </select>
          </label>
          <label className="checkbox-row">
            <input
              checked={isDefault}
              onChange={(event) => setIsDefault(event.target.checked)}
              type="checkbox"
            />
            设为该能力的默认模型
          </label>
          <button disabled={saving} type="submit">
            {saving ? '保存中…' : '保存'}
          </button>
        </form>
      </section>
    </div>
  );
}
