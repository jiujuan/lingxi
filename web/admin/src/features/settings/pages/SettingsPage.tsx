import { useEffect, useState } from 'react';

import { getSystemSettings, saveSystemSettings } from '../api/settingsApi';
import type { SystemSettings } from '../types';

export function SettingsPage() {
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [saved, setSaved] = useState<SystemSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    try {
      const result = await getSystemSettings();
      setSettings(result);
      setSaved(result);
      setError(null);
    } catch {
      setError('系统设置加载失败');
    }
  }

  async function submit() {
    if (!settings) return;
    if (isHighRiskChange(saved, settings) && !window.confirm('高风险设置会影响新任务或线上会话，确认保存？')) {
      return;
    }
    try {
      const result = await saveSystemSettings(settings);
      setSettings(result);
      setSaved(result);
      setError(null);
      setMessage('设置已保存');
    } catch {
      setError('保存失败，请检查字段；当前输入已保留');
    }
  }

  if (!settings) {
    return (
      <div className="page-stack">
        <section className="toolbar-row">
          <div>
            <p className="eyebrow">Settings</p>
            <h2>系统设置</h2>
          </div>
        </section>
        {error ? <div className="error-box">{error}</div> : <p className="muted">正在加载设置...</p>}
      </div>
    );
  }

  return (
    <div className="page-stack settings-page">
      <section className="toolbar-row">
        <div>
          <p className="eyebrow">Settings</p>
          <h2>系统设置</h2>
        </div>
        <div className="button-row">
          <button className="secondary-button" onClick={() => void load()} type="button">
            重新加载
          </button>
          <button onClick={() => void submit()} type="button">
            保存设置
          </button>
        </div>
      </section>
      {error ? <div className="error-box">{error}</div> : null}
      {message ? <p className="success-text">{message}</p> : null}

      <section className="two-column">
        <div className="panel form-grid">
          <h3>文件策略 <small>{settings.effectiveScopes.filePolicy}</small></h3>
          <label>
            最大文件大小 MB
            <input
              min={1}
              onChange={(event) => update('filePolicy', 'maxFileSizeMb', Number(event.target.value))}
              type="number"
              value={settings.filePolicy.maxFileSizeMb}
            />
          </label>
          <label>
            允许类型
            <input
              onChange={(event) => update('filePolicy', 'allowedExtensions', event.target.value.split(',').map((item) => item.trim()).filter(Boolean))}
              value={settings.filePolicy.allowedExtensions.join(',')}
            />
          </label>
          <label>
            默认解析器
            <select
              onChange={(event) => update('filePolicy', 'defaultParser', event.target.value)}
              value={settings.filePolicy.defaultParser}
            >
              <option value="lightweight">lightweight</option>
              <option value="mineru">mineru</option>
            </select>
          </label>
          <label className="checkbox-row">
            <input
              checked={settings.filePolicy.ocrEnabled}
              onChange={(event) => update('filePolicy', 'ocrEnabled', event.target.checked)}
              type="checkbox"
            />
            OCR
          </label>
          <label className="checkbox-row">
            <input
              checked={settings.filePolicy.fallbackEnabled}
              onChange={(event) => update('filePolicy', 'fallbackEnabled', event.target.checked)}
              type="checkbox"
            />
            fallback
          </label>
        </div>

        <div className="panel form-grid">
          <h3>检索策略 <small>{settings.effectiveScopes.retrievalPolicy}</small></h3>
          <label>
            Vector TopK
            <input min={1} onChange={(event) => update('retrievalPolicy', 'vectorTopK', Number(event.target.value))} type="number" value={settings.retrievalPolicy.vectorTopK} />
          </label>
          <label>
            Text TopK
            <input min={1} onChange={(event) => update('retrievalPolicy', 'textTopK', Number(event.target.value))} type="number" value={settings.retrievalPolicy.textTopK} />
          </label>
          <label>
            Final TopK
            <input min={1} onChange={(event) => update('retrievalPolicy', 'finalTopK', Number(event.target.value))} type="number" value={settings.retrievalPolicy.finalTopK} />
          </label>
          <label>
            低置信阈值
            <input
              max={2}
              min={0}
              onChange={(event) => update('retrievalPolicy', 'lowConfidenceThreshold', Number(event.target.value))}
              step={0.01}
              type="number"
              value={settings.retrievalPolicy.lowConfidenceThreshold}
            />
          </label>
        </div>
      </section>

      <section className="two-column">
        <div className="panel form-grid">
          <h3>限流与存储 <small>{settings.effectiveScopes.rateLimitPolicy}</small></h3>
          <label>
            API Key 默认限流 / min
            <input min={1} onChange={(event) => update('rateLimitPolicy', 'apiKeyDefaultPerMinute', Number(event.target.value))} type="number" value={settings.rateLimitPolicy.apiKeyDefaultPerMinute} />
          </label>
          <label>
            Chat 限流 / min
            <input min={1} onChange={(event) => update('rateLimitPolicy', 'chatPerMinute', Number(event.target.value))} type="number" value={settings.rateLimitPolicy.chatPerMinute} />
          </label>
          <label>
            存储后端
            <input onChange={(event) => update('storagePolicy', 'backend', event.target.value)} value={settings.storagePolicy.backend} />
          </label>
          <label>
            存储前缀
            <input onChange={(event) => update('storagePolicy', 'prefix', event.target.value)} value={settings.storagePolicy.prefix} />
          </label>
        </div>

        <div className="panel form-grid">
          <h3>数据保留 <small>{settings.effectiveScopes.retentionPolicy}</small></h3>
          <label>
            API 调用日志天数
            <input min={1} onChange={(event) => update('retentionPolicy', 'apiCallLogDays', Number(event.target.value))} type="number" value={settings.retentionPolicy.apiCallLogDays} />
          </label>
          <label>
            审计日志天数
            <input min={30} onChange={(event) => update('retentionPolicy', 'auditLogDays', Number(event.target.value))} type="number" value={settings.retentionPolicy.auditLogDays} />
          </label>
          <label>
            任务日志天数
            <input min={1} onChange={(event) => update('retentionPolicy', 'taskRunDays', Number(event.target.value))} type="number" value={settings.retentionPolicy.taskRunDays} />
          </label>
          <label>
            软删除保留天数
            <input min={1} onChange={(event) => update('retentionPolicy', 'softDeleteDays', Number(event.target.value))} type="number" value={settings.retentionPolicy.softDeleteDays} />
          </label>
        </div>
      </section>
    </div>
  );

  function update<K extends keyof SystemSettings, F extends keyof SystemSettings[K]>(
    section: K,
    field: F,
    value: SystemSettings[K][F],
  ) {
    setSettings((current) => {
      if (!current) return current;
      return {
        ...current,
        [section]: {
          ...(current[section] as object),
          [field]: value,
        },
      };
    });
  }
}

function isHighRiskChange(previous: SystemSettings | null, next: SystemSettings) {
  if (!previous) return true;
  return (
    previous.filePolicy.maxFileSizeMb !== next.filePolicy.maxFileSizeMb ||
    previous.retrievalPolicy.lowConfidenceThreshold !== next.retrievalPolicy.lowConfidenceThreshold ||
    previous.retentionPolicy.apiCallLogDays !== next.retentionPolicy.apiCallLogDays ||
    previous.retentionPolicy.auditLogDays !== next.retentionPolicy.auditLogDays
  );
}

