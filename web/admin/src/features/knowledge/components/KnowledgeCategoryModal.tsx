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
        aria-label={category ? '编辑项目 / 专题' : '新建项目 / 专题'}
        className="modal-panel"
        role="dialog"
      >
        <div className="toolbar-row compact">
          <h3>{category ? '编辑项目 / 专题' : '新建项目 / 专题'}</h3>
          <button className="secondary-button" disabled={saving} onClick={onClose} type="button">
            关闭
          </button>
        </div>
        {error ? <div className="error-box">{error}</div> : null}
        <form className="form-grid" onSubmit={(event) => void submit(event)}>
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
          <button disabled={saving} type="submit">
            {saving ? '保存中…' : '保存'}
          </button>
        </form>
      </section>
    </div>
  );
}
