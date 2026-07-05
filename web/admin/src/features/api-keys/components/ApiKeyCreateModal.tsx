import { useState } from 'react';

import type { ApiKeyCreatePayload, ApiKeyCreateResult } from '../types';

type Props = {
  createdKey: ApiKeyCreateResult | null;
  onClose: () => void;
  onCreate: (payload: ApiKeyCreatePayload) => Promise<void>;
};

export function ApiKeyCreateModal({ createdKey, onClose, onCreate }: Props) {
  const [name, setName] = useState('Internal Copilot');
  const [scopes, setScopes] = useState('chat:read,knowledge:query');
  const [rateLimit, setRateLimit] = useState(60);

  return (
    <div className="modal-backdrop" role="presentation">
      <section aria-label="创建 API Key" className="modal-panel" role="dialog">
        <div className="toolbar-row compact">
          <h3>创建 API Key</h3>
          <button className="secondary-button" onClick={onClose} type="button">
            关闭
          </button>
        </div>
        {createdKey ? (
          <div className="api-key-secret">
            <span className="field-label">明文 Key 只展示一次</span>
            <code>{createdKey.key}</code>
            <p className="muted">{createdKey.warning}</p>
          </div>
        ) : (
          <form
            className="form-grid"
            onSubmit={(event) => {
              event.preventDefault();
              void onCreate({
                name,
                scopes: scopes
                  .split(',')
                  .map((item) => item.trim())
                  .filter(Boolean),
                allowedDepartmentIds: [],
                allowedRoleIds: [],
                rateLimitPerMinute: rateLimit,
              });
            }}
          >
            <label>
              名称
              <input onChange={(event) => setName(event.target.value)} value={name} />
            </label>
            <label>
              Scope
              <input onChange={(event) => setScopes(event.target.value)} value={scopes} />
            </label>
            <label>
              每分钟限流
              <input
                min={1}
                onChange={(event) => setRateLimit(Number(event.target.value))}
                type="number"
                value={rateLimit}
              />
            </label>
            <button type="submit">创建</button>
          </form>
        )}
      </section>
    </div>
  );
}
