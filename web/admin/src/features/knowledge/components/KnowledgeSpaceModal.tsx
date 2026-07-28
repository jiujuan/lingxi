import { FormEvent, useEffect, useState } from 'react';

import { errorMessage } from '../../../api/client';
import type {
  CreateKnowledgeSpacePayload,
  KnowledgeSpace,
  UpdateKnowledgeSpacePayload,
} from '../types/classification';

type Props = {
  space: KnowledgeSpace | null;
  onClose: () => void;
  onSubmit: (payload: CreateKnowledgeSpacePayload | UpdateKnowledgeSpacePayload) => Promise<void>;
};

export function KnowledgeSpaceModal({ space, onClose, onSubmit }: Props) {
  const [name, setName] = useState(space?.name ?? '');
  const [code, setCode] = useState(space?.code ?? '');
  const [description, setDescription] = useState(space?.description ?? '');
  const [sortOrder, setSortOrder] = useState(String(space?.sortOrder ?? 0));
  const [status, setStatus] = useState(space?.status ?? 'ACTIVE');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setName(space?.name ?? '');
    setCode(space?.code ?? '');
    setDescription(space?.description ?? '');
    setSortOrder(String(space?.sortOrder ?? 0));
    setStatus(space?.status ?? 'ACTIVE');
    setError(null);
  }, [space]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSubmit({
        name: name.trim(),
        code: code.trim(),
        description: description.trim() || null,
        sortOrder: Number.parseInt(sortOrder, 10) || 0,
        status,
      });
      onClose();
    } catch (caught) {
      setError(errorMessage(caught, '知识库空间保存失败。'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        aria-label={space ? '编辑知识库空间' : '新建知识库空间'}
        className="modal-panel"
        role="dialog"
      >
        <div className="toolbar-row compact">
          <h3>{space ? '编辑知识库空间' : '新建知识库空间'}</h3>
          <button className="secondary-button" disabled={saving} onClick={onClose} type="button">
            关闭
          </button>
        </div>
        {error ? <div className="error-box">{error}</div> : null}
        <form className="form-grid" onSubmit={(event) => void submit(event)}>
          <label>
            空间名称
            <input onChange={(event) => setName(event.target.value)} required value={name} />
          </label>
          <label>
            空间编码
            <input
              onChange={(event) => setCode(event.target.value)}
              placeholder="如 customer-knowledge"
              required
              value={code}
            />
          </label>
          <label>
            描述
            <textarea
              onChange={(event) => setDescription(event.target.value)}
              placeholder="可选"
              rows={3}
              value={description}
            />
          </label>
          <div className="filter-grid">
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
          <button disabled={saving} type="submit">
            {saving ? '保存中…' : '保存'}
          </button>
        </form>
      </section>
    </div>
  );
}
