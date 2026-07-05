import { FormEvent, useEffect, useState } from 'react';

import { updateDocumentPermissions, type KnowledgeDocument } from '../api/documentApi';
import type { PermissionPayload } from '../api/importJobApi';

type Props = {
  document: KnowledgeDocument | null;
  onClose: () => void;
  onSaved: () => void;
};

export function DocumentPermissionModal({ document, onClose, onSaved }: Props) {
  const [allAuthenticated, setAllAuthenticated] = useState(false);
  const [departmentIds, setDepartmentIds] = useState('');
  const [roleIds, setRoleIds] = useState('');
  const [userIds, setUserIds] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!document) {
      return;
    }
    setAllAuthenticated(document.permissions.allAuthenticated);
    setDepartmentIds(document.permissions.departments.map((item) => item.id).join(','));
    setRoleIds(document.permissions.roles.map((item) => item.id).join(','));
    setUserIds(document.permissions.users.map((item) => item.id).join(','));
    setError(null);
  }, [document]);

  if (!document) {
    return null;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!document) {
      return;
    }
    const payload: PermissionPayload = {
      allAuthenticated,
      departmentIds: splitIds(departmentIds),
      roleIds: splitIds(roleIds),
      userIds: splitIds(userIds),
    };
    const noAccessScope = !payload.allAuthenticated && !payload.departmentIds?.length && !payload.roleIds?.length && !payload.userIds?.length;
    const message = noAccessScope
      ? '当前权限为空，保存后该文档仅系统管理员可见。确认保存？'
      : '权限变更会立即影响新检索，确认保存？';
    if (!window.confirm(message)) {
      return;
    }

    setBusy(true);
    setError(null);
    try {
      await updateDocumentPermissions(document.id, payload);
      onSaved();
    } catch (caught) {
      setError(readError(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <form aria-modal="true" className="modal-panel" onSubmit={(event) => void submit(event)} role="dialog">
        <div className="toolbar-row compact">
          <div>
            <h3>编辑权限</h3>
            <p className="muted">{document.title}</p>
          </div>
          <button className="secondary-button" onClick={onClose} type="button">
            关闭
          </button>
        </div>
        <label className="checkbox-row">
          <input
            checked={allAuthenticated}
            onChange={(event) => setAllAuthenticated(event.target.checked)}
            type="checkbox"
          />
          全部登录用户可访问
        </label>
        <label>
          部门 ID
          <input
            disabled={allAuthenticated}
            onChange={(event) => setDepartmentIds(event.target.value)}
            value={departmentIds}
          />
        </label>
        <label>
          角色 ID
          <input
            disabled={allAuthenticated}
            onChange={(event) => setRoleIds(event.target.value)}
            value={roleIds}
          />
        </label>
        <label>
          用户 ID
          <input
            disabled={allAuthenticated}
            onChange={(event) => setUserIds(event.target.value)}
            value={userIds}
          />
        </label>
        {error ? <p className="error">{error}</p> : null}
        <button disabled={busy} type="submit">
          {busy ? '保存中' : '保存权限'}
        </button>
      </form>
    </div>
  );
}

function splitIds(value: string) {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function readError(error: unknown) {
  if (typeof error === 'object' && error && 'error' in error) {
    const payload = error as { error?: { message?: string } };
    return payload.error?.message || '请求失败。';
  }
  return '请求失败。';
}
