import { useState } from 'react';

import { errorMessage } from '../../../api/client';
import type { Department, DepartmentPayload } from '../types';

type Props = {
  /** null = create mode */
  department: Department | null;
  departments: Department[];
  onClose: () => void;
  onSubmit: (payload: DepartmentPayload) => Promise<void>;
};

export function DepartmentFormModal({ department, departments, onClose, onSubmit }: Props) {
  const [name, setName] = useState(department?.name ?? '');
  const [code, setCode] = useState(department?.code ?? '');
  const [parentId, setParentId] = useState(department?.parentId ?? '');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Backend rejects deeper cycles; hiding the department itself covers the
  // obvious case in the picker.
  const parentOptions = departments.filter((item) => item.id !== department?.id);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await onSubmit({ name, code, parentId: parentId || null });
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
        aria-label={department ? '编辑部门' : '新建部门'}
        className="modal-panel"
        role="dialog"
      >
        <div className="toolbar-row compact">
          <h3>{department ? '编辑部门' : '新建部门'}</h3>
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
            部门名称
            <input
              onChange={(event) => setName(event.target.value)}
              required
              value={name}
            />
          </label>
          <label>
            部门编码
            <input
              onChange={(event) => setCode(event.target.value)}
              placeholder="如 RD、HR"
              required
              value={code}
            />
          </label>
          <label>
            上级部门
            <select onChange={(event) => setParentId(event.target.value)} value={parentId}>
              <option value="">（无 · 作为顶级部门）</option>
              {parentOptions.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}（{item.code}）
                </option>
              ))}
            </select>
          </label>
          <button disabled={saving} type="submit">
            {saving ? '保存中…' : '保存'}
          </button>
        </form>
      </section>
    </div>
  );
}
