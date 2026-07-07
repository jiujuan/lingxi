import { useState } from 'react';

import { errorMessage } from '../../../api/client';
import type { AdminUser } from '../types';

type Props = {
  user: AdminUser;
  onClose: () => void;
  onSubmit: (userId: string, password: string) => Promise<void>;
};

export function ResetPasswordModal({ user, onClose, onSubmit }: Props) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await onSubmit(user.id, password);
      onClose();
    } catch (err) {
      setError(errorMessage(err, '重置失败'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section aria-label="重置密码" className="modal-panel" role="dialog">
        <div className="toolbar-row compact">
          <h3>重置密码</h3>
          <button className="secondary-button" onClick={onClose} type="button">
            关闭
          </button>
        </div>
        <p className="muted">
          为 {user.name}（{user.email}）设置新密码，重置后其已登录会话会立即失效。
        </p>
        {error ? <div className="error-box">{error}</div> : null}
        <form
          className="form-grid"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label>
            新密码
            <input
              minLength={8}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="至少 8 位"
              required
              type="password"
              value={password}
            />
          </label>
          <button disabled={saving} type="submit">
            {saving ? '提交中…' : '重置密码'}
          </button>
        </form>
      </section>
    </div>
  );
}
