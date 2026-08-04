import { useState } from 'react';

import { errorMessage } from '../../../api/client';
import type { ModelConfig, ModelConfigUpdatePayload } from '../api/modelConfigApi';

type Props = {
  config: ModelConfig;
  onClose: () => void;
  onSubmit: (configId: string, payload: ModelConfigUpdatePayload) => Promise<void>;
};

function configuredNumber(config: Record<string, unknown>, key: string, fallback: number) {
  const value = config[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

export function ModelConfigEditModal({ config, onClose, onSubmit }: Props) {
  const [modelName, setModelName] = useState(config.modelName);
  const [timeoutMs, setTimeoutMs] = useState(config.timeoutMs);
  const [connectTimeoutMs, setConnectTimeoutMs] = useState(
    config.connectTimeoutMs ?? Math.min(config.timeoutMs, 10000),
  );
  const [writeTimeoutMs, setWriteTimeoutMs] = useState(
    config.writeTimeoutMs ?? config.timeoutMs,
  );
  const [readIdleTimeoutMs, setReadIdleTimeoutMs] = useState(
    config.readIdleTimeoutMs ?? config.timeoutMs,
  );
  const [overallTimeoutMs, setOverallTimeoutMs] = useState(
    config.overallTimeoutMs ?? config.timeoutMs,
  );
  const [maxTokens, setMaxTokens] = useState(config.maxTokens?.toString() ?? '');
  const [embeddingDimension, setEmbeddingDimension] = useState(
    config.embeddingDimension?.toString() ?? '',
  );
  const qaSplit = (config.config.qaSplit ?? {}) as Record<string, unknown>;
  const [maxInputTokens, setMaxInputTokens] = useState(
    String(configuredNumber(qaSplit, 'maxInputTokens', 4096)),
  );
  const [reservedOutputTokens, setReservedOutputTokens] = useState(
    String(configuredNumber(qaSplit, 'reservedOutputTokens', 2048)),
  );
  const [maxRetries, setMaxRetries] = useState(
    String(configuredNumber(qaSplit, 'maxRetries', 1)),
  );
  const [maxSplitDepth, setMaxSplitDepth] = useState(
    String(configuredNumber(qaSplit, 'maxSplitDepth', 1)),
  );
  const [isDefault, setIsDefault] = useState(config.isDefault);
  const [status, setStatus] = useState(config.status);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit() {
    if (
      [connectTimeoutMs, writeTimeoutMs, readIdleTimeoutMs, overallTimeoutMs].some(
        (value) => !Number.isInteger(value) || value < 100,
      )
    ) {
      setError('四阶段超时都必须是不小于 100ms 的整数。');
      return;
    }
    if (overallTimeoutMs < readIdleTimeoutMs) {
      setError('单次调用总超时不能小于首 Token/读取空闲超时。');
      return;
    }
    setSaving(true);
    setError(null);
    const payload: ModelConfigUpdatePayload = {
      modelName,
      timeoutMs,
      connectTimeoutMs,
      writeTimeoutMs,
      readIdleTimeoutMs,
      overallTimeoutMs,
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
    if (config.capability === 'QA_SPLIT') {
      payload.config = {
        ...config.config,
        qaSplit: {
          ...qaSplit,
          maxInputTokens: Number(maxInputTokens),
          reservedOutputTokens: Number(reservedOutputTokens),
          maxRetries: Number(maxRetries),
          maxSplitDepth: Number(maxSplitDepth),
        },
      };
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
      <section
        aria-label="编辑模型实例"
        className="modal-panel model-config-edit-modal"
        role="dialog"
      >
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
          {config.capability === 'QA_SPLIT' ? (
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
