import { FormEvent, useEffect, useMemo, useState } from 'react';

import { errorMessage } from '../../../api/client';
import type { Department, DepartmentPayload } from '../../org/types';

type Props = {
  department: Department | null;
  departments: Department[];
  onClose: () => void;
  onSubmit: (payload: DepartmentPayload) => Promise<void>;
};

export function ClassificationDepartmentModal({
  department,
  departments,
  onClose,
  onSubmit,
}: Props) {
  const [name, setName] = useState(department?.name ?? '');
  const [code, setCode] = useState(department?.code ?? '');
  const [parentId, setParentId] = useState(department?.parentId ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const parentOptions = useMemo(
    () => departments.filter((item) => item.id !== department?.id),
    [department?.id, departments],
  );

  useEffect(() => {
    setName(department?.name ?? '');
    setCode(department?.code ?? '');
    setParentId(department?.parentId ?? '');
    setError(null);
  }, [department]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSubmit({
        name: name.trim(),
        code: code.trim(),
        parentId: parentId || null,
      });
      onClose();
    } catch (caught) {
      setError(errorMessage(caught, '部门保存失败。'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        aria-label={department ? '编辑部门' : '增加部门'}
        aria-modal="true"
        className="modal-panel classification-form-modal"
        role="dialog"
      >
        <header className="classification-modal-header">
          <h3>{department ? '编辑部门' : '增加部门'}</h3>
          <button
            aria-label="关闭"
            className="icon-button"
            disabled={saving}
            onClick={onClose}
            type="button"
          >
            <CloseIcon />
          </button>
        </header>
        {error ? <div className="error-box">{error}</div> : null}
        <form className="classification-form" onSubmit={(event) => void submit(event)}>
          <label>
            部门名称
            <input onChange={(event) => setName(event.target.value)} required value={name} />
          </label>
          <label>
            部门编码
            <input
              onChange={(event) => setCode(event.target.value)}
              placeholder="如 operations"
              required
              value={code}
            />
          </label>
          <label>
            上级部门
            <select onChange={(event) => setParentId(event.target.value)} value={parentId}>
              <option value="">无（顶级部门）</option>
              {parentOptions.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}（{item.code}）
                </option>
              ))}
            </select>
          </label>
          <footer className="classification-modal-actions">
            <button
              className="secondary-button"
              disabled={saving}
              onClick={onClose}
              type="button"
            >
              取消
            </button>
            <button disabled={saving} type="submit">
              {saving ? '保存中…' : '保存'}
            </button>
          </footer>
        </form>
      </section>
    </div>
  );
}

function CloseIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="m7 7 10 10M17 7 7 17" />
    </svg>
  );
}
