import { FormEvent, useEffect, useState } from 'react';

import { errorMessage } from '../../../api/client';
import type { Department } from '../../org/types';
import type {
  CreateKnowledgeCategoryPayload,
  KnowledgeCategory,
  KnowledgeCategoryType,
  KnowledgeSpace,
  UpdateKnowledgeCategoryPayload,
} from '../types/classification';

type Props = {
  category: KnowledgeCategory | null;
  spaces: KnowledgeSpace[];
  departments: Department[];
  defaultSpaceId: string;
  defaultDepartmentId: string;
  onClose: () => void;
  onSubmit: (
    payload: CreateKnowledgeCategoryPayload | UpdateKnowledgeCategoryPayload,
  ) => Promise<void>;
};

export function KnowledgeCategoryModal({
  category,
  spaces,
  departments,
  defaultSpaceId,
  defaultDepartmentId,
  onClose,
  onSubmit,
}: Props) {
  const [spaceId, setSpaceId] = useState(category?.spaceId ?? defaultSpaceId);
  const [departmentId, setDepartmentId] = useState(category?.departmentId ?? defaultDepartmentId);
  const [name, setName] = useState(category?.name ?? '');
  const [code, setCode] = useState(category?.code ?? '');
  const [categoryType, setCategoryType] = useState<KnowledgeCategoryType>(
    category?.categoryType ?? 'TOPIC',
  );
  const [description, setDescription] = useState(category?.description ?? '');
  const [sortOrder, setSortOrder] = useState(String(category?.sortOrder ?? 0));
  const [status, setStatus] = useState(category?.status ?? 'ACTIVE');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSpaceId(category?.spaceId ?? defaultSpaceId);
    setDepartmentId(category?.departmentId ?? defaultDepartmentId);
    setName(category?.name ?? '');
    setCode(category?.code ?? '');
    setCategoryType(category?.categoryType ?? 'TOPIC');
    setDescription(category?.description ?? '');
    setSortOrder(String(category?.sortOrder ?? 0));
    setStatus(category?.status ?? 'ACTIVE');
    setError(null);
  }, [category, defaultDepartmentId, defaultSpaceId]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!spaceId || !departmentId) {
      setError('请选择知识库空间和分类部门。');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSubmit({
        spaceId,
        departmentId,
        name: name.trim(),
        code: code.trim(),
        categoryType,
        description: description.trim() || null,
        parentId: null,
        sortOrder: Number.parseInt(sortOrder, 10) || 0,
        status,
      });
      onClose();
    } catch (caught) {
      setError(errorMessage(caught, '项目 / 专题保存失败。'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        aria-label={category ? '编辑专题 / 项目' : '增加专题 / 项目'}
        aria-modal="true"
        className="modal-panel classification-form-modal"
        role="dialog"
      >
        <header className="classification-modal-header">
          <h3>{category ? '编辑专题 / 项目' : '增加专题 / 项目'}</h3>
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
          <div className="filter-grid">
            <label>
              知识库空间
              <select onChange={(event) => setSpaceId(event.target.value)} required value={spaceId}>
                <option value="">请选择空间</option>
                {spaces.map((space) => (
                  <option key={space.id} value={space.id}>
                    {space.name}（{space.code}）
                  </option>
                ))}
              </select>
            </label>
            <label>
              分类部门
              <select
                onChange={(event) => setDepartmentId(event.target.value)}
                required
                value={departmentId}
              >
                <option value="">请选择部门</option>
                {departments.map((department) => (
                  <option key={department.id} value={department.id}>
                    {department.name}（{department.code}）
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label>
            名称
            <input onChange={(event) => setName(event.target.value)} required value={name} />
          </label>
          <label>
            编码
            <input
              onChange={(event) => setCode(event.target.value)}
              placeholder="如 refund-policy"
              required
              value={code}
            />
          </label>
          <div className="filter-grid">
            <label>
              类型
              <select
                onChange={(event) => setCategoryType(event.target.value as KnowledgeCategoryType)}
                value={categoryType}
              >
                <option value="PROJECT">项目</option>
                <option value="TOPIC">专题</option>
              </select>
            </label>
            <label>
              排序
              <input
                min={0}
                onChange={(event) => setSortOrder(event.target.value)}
                type="number"
                value={sortOrder}
              />
            </label>
            <label>
              状态
              <select onChange={(event) => setStatus(event.target.value)} value={status}>
                <option value="ACTIVE">启用</option>
                <option value="INACTIVE">停用</option>
              </select>
            </label>
          </div>
          <label>
            描述
            <textarea
              onChange={(event) => setDescription(event.target.value)}
              placeholder="可选"
              rows={3}
              value={description}
            />
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
