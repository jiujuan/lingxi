import { FormEvent, useEffect, useState } from 'react';

import { errorMessage } from '../../../api/client';
import {
  bulkUpdateDocumentClassification,
  type KnowledgeDocument,
} from '../api/documentApi';
import { validateClassificationValue } from '../hooks/useKnowledgeClassificationOptions';
import type { KnowledgeClassificationValue } from '../types/classification';
import {
  formatClassificationPath,
  KnowledgeClassificationSelect,
  toClassificationPayload,
} from './KnowledgeClassificationSelect';

type Props = {
  documents: KnowledgeDocument[];
  onClose: () => void;
  onSaved: () => void;
};

const EMPTY_CLASSIFICATION: KnowledgeClassificationValue = {
  spaceId: null,
  departmentId: null,
  categoryId: null,
};

export function BulkDocumentClassificationModal({ documents, onClose, onSaved }: Props) {
  const [value, setValue] = useState<KnowledgeClassificationValue>(EMPTY_CLASSIFICATION);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setValue(EMPTY_CLASSIFICATION);
    setError(null);
  }, [documents]);

  if (!documents.length) {
    return null;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const validation = validateClassificationValue(value, { allowUnclassified: true });
    if (validation) {
      setError(validation);
      return;
    }

    setBusy(true);
    setError(null);
    try {
      await bulkUpdateDocumentClassification({
        documentIds: documents.map((document) => document.id),
        classification: toClassificationPayload(value),
      });
      onSaved();
    } catch (caught) {
      setError(errorMessage(caught, '批量归类失败。'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <form
        aria-modal="true"
        className="modal-panel bulk-classification-modal"
        onSubmit={(event) => void handleSubmit(event)}
        role="dialog"
      >
        <div className="toolbar-row compact">
          <div>
            <h3>批量归类</h3>
            <p className="muted">已选择 {documents.length} 篇文档。</p>
          </div>
          <button className="secondary-button" disabled={busy} onClick={onClose} type="button">
            关闭
          </button>
        </div>

        <div className="bulk-document-list" aria-label="已选择文档">
          {documents.slice(0, 5).map((document) => (
            <p key={document.id}>
              <strong>{document.title}</strong>
              <span>当前：{formatClassificationPath(document.classification)}</span>
            </p>
          ))}
          {documents.length > 5 ? (
            <p className="muted">另有 {documents.length - 5} 篇文档未展开显示。</p>
          ) : null}
        </div>

        <KnowledgeClassificationSelect
          allowUnclassified
          disabled={busy}
          idPrefix="bulk-document-classification"
          legend="选择目标分类（留空将清空分类）"
          onChange={setValue}
          showValidation
          value={value}
        />

        <p className="muted">提交后后端会一次性校验全部文档权限；任一文档无权限时不会部分更新。</p>
        {error ? <p className="error">{error}</p> : null}

        <div className="button-row">
          <button disabled={busy} type="submit">
            {busy ? '提交中' : '确认批量归类'}
          </button>
          <button className="secondary-button" disabled={busy} onClick={onClose} type="button">
            取消
          </button>
        </div>
      </form>
    </div>
  );
}
