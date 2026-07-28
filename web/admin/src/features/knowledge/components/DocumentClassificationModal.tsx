import { FormEvent, useEffect, useState } from 'react';

import { errorMessage } from '../../../api/client';
import { updateDocumentClassification, type KnowledgeDocument } from '../api/documentApi';
import { validateClassificationValue } from '../hooks/useKnowledgeClassificationOptions';
import type {
  KnowledgeClassificationValue,
  UpdateDocumentClassificationPayload,
} from '../types/classification';
import {
  formatClassificationPath,
  KnowledgeClassificationSelect,
  toClassificationPayload,
} from './KnowledgeClassificationSelect';

type DocumentClassificationTarget = Pick<KnowledgeDocument, 'id' | 'title' | 'classification'>;

type Props = {
  document: DocumentClassificationTarget | null;
  onClose: () => void;
  onSaved: () => void;
};

export function DocumentClassificationModal({ document, onClose, onSaved }: Props) {
  const [value, setValue] = useState<KnowledgeClassificationValue>(() =>
    normalizeInitialClassification(document),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setValue(normalizeInitialClassification(document));
    setError(null);
  }, [document]);

  if (!document) {
    return null;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!document) {
      return;
    }

    const validation = validateClassificationValue(value, { allowUnclassified: true });
    if (validation) {
      setError(validation);
      return;
    }

    setBusy(true);
    setError(null);
    try {
      await updateDocumentClassification(document.id, buildPayload(value));
      onSaved();
    } catch (caught) {
      setError(errorMessage(caught, '分类保存失败。'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <form
        aria-modal="true"
        className="modal-panel"
        onSubmit={(event) => void handleSubmit(event)}
        role="dialog"
      >
        <div className="toolbar-row compact">
          <div>
            <h3>编辑分类</h3>
            <p className="muted">{document.title}</p>
          </div>
          <button className="secondary-button" disabled={busy} onClick={onClose} type="button">
            关闭
          </button>
        </div>

        <p className="muted">当前分类：{formatClassificationPath(document.classification)}</p>

        <KnowledgeClassificationSelect
          allowUnclassified
          disabled={busy}
          idPrefix="document-classification-edit"
          legend="选择新的分类"
          onChange={setValue}
          showValidation
          value={value}
        />

        {error ? <p className="error">{error}</p> : null}

        <div className="button-row">
          <button disabled={busy} type="submit">
            {busy ? '保存中' : '保存分类'}
          </button>
          <button className="secondary-button" disabled={busy} onClick={onClose} type="button">
            取消
          </button>
        </div>
      </form>
    </div>
  );
}

function normalizeInitialClassification(
  document: DocumentClassificationTarget | null,
): KnowledgeClassificationValue {
  return {
    spaceId: document?.classification?.spaceId ?? null,
    departmentId: document?.classification?.departmentId ?? null,
    categoryId: document?.classification?.categoryId ?? null,
  };
}

function buildPayload(value: KnowledgeClassificationValue): UpdateDocumentClassificationPayload {
  return (
    toClassificationPayload(value) ?? {
      spaceId: null,
      departmentId: null,
      categoryId: null,
    }
  );
}
