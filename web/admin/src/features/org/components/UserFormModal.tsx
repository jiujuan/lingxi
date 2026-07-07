import { useState } from 'react';

import { errorMessage } from '../../../api/client';
import type { AdminUser, Department, Role, UserCreatePayload, UserPayload } from '../types';

type Props = {
  /** null = create mode */
  user: AdminUser | null;
  departments: Department[];
  roles: Role[];
  onClose: () => void;
  onCreate: (payload: UserCreatePayload) => Promise<void>;
  onUpdate: (userId: string, payload: UserPayload) => Promise<void>;
};

export function UserFormModal({ user, departments, roles, onClose, onCreate, onUpdate }: Props) {
  const [email, setEmail] = useState(user?.email ?? '');
  const [name, setName] = useState(user?.name ?? '');
  const [password, setPassword] = useState('');
  const [departmentId, setDepartmentId] = useState(user?.departmentId ?? '');
  const [roleIds, setRoleIds] = useState<string[]>(user?.roles.map((role) => role.id) ?? []);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function toggleRole(roleId: string) {
    setRoleIds((current) =>
      current.includes(roleId)
        ? current.filter((id) => id !== roleId)
        : [...current, roleId],
    );
  }

  async function submit() {
    setSaving(true);
    setError(null);
    const payload: UserPayload = {
      email,
      name,
      departmentId: departmentId || null,
      roleIds,
    };
    try {
      if (user) {
        await onUpdate(user.id, payload);
      } else {
        await onCreate({ ...payload, password });
      }
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
        aria-label={user ? '编辑用户' : '新建用户'}
        className="modal-panel"
        role="dialog"
      >
        <div className="toolbar-row compact">
          <h3>{user ? '编辑用户' : '新建用户'}</h3>
          <button className="secondary-button" onClick={onClose} type="button">
            关闭
          </button>
        </div>
        {error ? <div className="error-box">{error}</div> : null}
        <form
          className="form-grid"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label>
            邮箱
            <input
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </label>
          <label>
            姓名
            <input
              onChange={(event) => setName(event.target.value)}
              required
              value={name}
            />
          </label>
          {user ? null : (
            <label>
              初始密码
              <input
                minLength={8}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="至少 8 位"
                required
                type="password"
                value={password}
              />
            </label>
          )}
          <label>
            所属部门
            <select
              onChange={(event) => setDepartmentId(event.target.value)}
              value={departmentId}
            >
              <option value="">（未分配）</option>
              {departments.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}（{item.code}）
                </option>
              ))}
            </select>
          </label>
          <div>
            <span className="field-label">角色</span>
            {roles.length === 0 ? <p className="muted">暂无可分配角色</p> : null}
            {roles.map((role) => (
              <label className="checkbox-row" key={role.id}>
                <input
                  checked={roleIds.includes(role.id)}
                  onChange={() => toggleRole(role.id)}
                  type="checkbox"
                />
                {role.name}（{role.code}）
              </label>
            ))}
          </div>
          <button disabled={saving} type="submit">
            {saving ? '保存中…' : '保存'}
          </button>
        </form>
      </section>
    </div>
  );
}
