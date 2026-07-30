import { useQuery } from '@tanstack/react-query';
import { type MouseEvent, useEffect, useMemo, useState } from 'react';

import { errorMessage } from '../../../api/client';
import {
  createRole,
  getRole,
  listAvailablePermissions,
  updateRole,
} from '../api/roleApi';
import type { RolePermission } from '../types';

export type RoleFormMode = 'create' | 'edit' | 'view';

type Props = {
  mode: RoleFormMode;
  roleId?: string;
  onClose: () => void;
  onSaved: () => Promise<void>;
};

type FormValues = {
  name: string;
  code: string;
  permissionIds: string[];
};

const EMPTY_VALUES: FormValues = {
  name: '',
  code: '',
  permissionIds: [],
};

export function RoleFormModal({ mode, roleId, onClose, onSaved }: Props) {
  const [values, setValues] = useState<FormValues>(EMPTY_VALUES);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const isReadOnly = mode === 'view';
  const shouldLoadRole = mode !== 'create' && Boolean(roleId);
  const roleQuery = useQuery({
    queryKey: ['roles', 'detail', roleId],
    queryFn: () => getRole(roleId ?? ''),
    enabled: shouldLoadRole,
  });
  const permissionsQuery = useQuery({
    queryKey: ['roles', 'available-permissions'],
    queryFn: listAvailablePermissions,
  });

  useEffect(() => {
    if (!roleQuery.data) {
      return;
    }
    setValues({
      name: roleQuery.data.name,
      code: roleQuery.data.code,
      permissionIds: roleQuery.data.permissions.map((permission) => permission.id),
    });
  }, [roleQuery.data]);

  const permissions = useMemo(() => permissionsQuery.data?.data ?? [], [permissionsQuery.data]);
  const groupedPermissions = useMemo(() => groupPermissions(permissions), [permissions]);
  const isLoading = roleQuery.isLoading || permissionsQuery.isLoading;
  const loadError = roleQuery.isError
    ? errorMessage(roleQuery.error, '角色详情加载失败')
    : permissionsQuery.isError
      ? errorMessage(permissionsQuery.error, '权限目录加载失败')
      : null;

  function updateValue<K extends keyof FormValues>(key: K, value: FormValues[K]) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  function togglePermission(permissionId: string) {
    setValues((current) => ({
      ...current,
      permissionIds: current.permissionIds.includes(permissionId)
        ? current.permissionIds.filter((id) => id !== permissionId)
        : [...current.permissionIds, permissionId],
    }));
  }

  function closeOnBackdrop(event: MouseEvent<HTMLDivElement>) {
    if (!saving && event.target === event.currentTarget) {
      onClose();
    }
  }

  async function submit() {
    const name = values.name.trim();
    const code = values.code.trim().toUpperCase();
    if (!name) {
      setError('角色名称不能为空');
      return;
    }
    if (!code) {
      setError('角色编码不能为空');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = { name, code, permissionIds: values.permissionIds };
      if (mode === 'create') {
        await createRole(payload);
      } else {
        if (!roleId) {
          setError('角色标识无效');
          return;
        }
        await updateRole(roleId, payload);
      }
      await onSaved();
      onClose();
    } catch (err) {
      setError(errorMessage(err, '保存角色失败'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={closeOnBackdrop} role="presentation">
      <section
        aria-label={modalTitle(mode)}
        aria-modal="true"
        className="modal-panel role-form-modal"
        role="dialog"
      >
        <div className="toolbar-row compact">
          <h3>{modalTitle(mode)}</h3>
          <button className="secondary-button" disabled={saving} onClick={onClose} type="button">
            关闭
          </button>
        </div>
        {loadError ? <div className="error-box">{loadError}</div> : null}
        {error ? <div className="error-box">{error}</div> : null}
        {isLoading ? <p className="muted">正在加载角色数据…</p> : null}
        {!isLoading && !loadError ? (
          <form
            className="form-grid"
            onSubmit={(event) => {
              event.preventDefault();
              if (!isReadOnly) {
                void submit();
              }
            }}
          >
            <label>
              名称
              <input
                disabled={isReadOnly || saving}
                maxLength={120}
                onChange={(event) => updateValue('name', event.target.value)}
                required
                value={values.name}
              />
            </label>
            <label>
              编码
              <input
                disabled={isReadOnly || saving}
                maxLength={80}
                onChange={(event) => updateValue('code', event.target.value.toUpperCase())}
                required
                value={values.code}
              />
            </label>
            <label>
              作用范围
              <input disabled value="TENANT" />
            </label>
            <div className="role-permission-groups">
              <span className="field-label">权限</span>
              {Object.entries(groupedPermissions).map(([module, modulePermissions]) => (
                <fieldset className="role-permission-group" key={module}>
                  <legend>{module}</legend>
                  {modulePermissions.map((permission) => (
                    <label className="checkbox-row" key={permission.id}>
                      <input
                        checked={values.permissionIds.includes(permission.id)}
                        disabled={isReadOnly || saving}
                        onChange={() => togglePermission(permission.id)}
                        type="checkbox"
                      />
                      <span>
                        {permission.code}
                        {permission.description ? `：${permission.description}` : ''}
                      </span>
                    </label>
                  ))}
                </fieldset>
              ))}
              {permissions.length === 0 ? <p className="muted">暂无可分配权限</p> : null}
            </div>
            {!isReadOnly ? (
              <button disabled={saving} type="submit">
                {saving ? '保存中…' : '保存'}
              </button>
            ) : null}
          </form>
        ) : null}
      </section>
    </div>
  );
}

function modalTitle(mode: RoleFormMode) {
  if (mode === 'create') {
    return '新增角色';
  }
  return mode === 'edit' ? '编辑角色' : '查看角色';
}

function groupPermissions(permissions: RolePermission[]) {
  return permissions.reduce<Record<string, RolePermission[]>>((groups, permission) => {
    const module = permission.module || 'OTHER';
    if (!groups[module]) {
      groups[module] = [];
    }
    groups[module].push(permission);
    return groups;
  }, {});
}
