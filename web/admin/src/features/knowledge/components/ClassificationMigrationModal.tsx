import type { FormEvent } from 'react';
import { useEffect, useState } from 'react';

import { errorMessage } from '../../../api/client';
import { migrateCategoryDocuments, migrateSpaceDocuments } from '../api/classificationApi';
import { validateClassificationValue } from '../hooks/useKnowledgeClassificationOptions';
import type { KnowledgeClassificationValue } from '../types/classification';
import {
  KnowledgeClassificationSelect,
  toClassificationPayload,
} from './KnowledgeClassificationSelect';

export type ClassificationMigrationSource =
  | { type: 'SPACE'; id: string; name: string; documentCount: number }
  | { type: 'CATEGORY'; id: string; name: string; documentCount: number };

type Props = {
  source: ClassificationMigrationSource;
  onClose: () => void;
  onMigrated: () => void;
};

const EMPTY_CLASSIFICATION: KnowledgeClassificationValue = {
  spaceId: null,
  departmentId: null,
  categoryId: null,
};

export function ClassificationMigrationModal({ source, onClose, onMigrated }: Props) {
  const [value, setValue] = useState<KnowledgeClassificationValue>(EMPTY_CLASSIFICATION);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setValue(EMPTY_CLASSIFICATION);
    setError(null);
  }, [source]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();

    const validation = validateClassificationValue(value, {
      required: true,
      allowUnclassified: false,
    });
    if (validation) {
      setError(validation);
      return;
    }
    if (source.type === 'SPACE' && value.spaceId === source.id) {
      setError('空间删除迁移必须选择其他知识库空间下的目标分类。');
      return;
    }
    if (source.type === 'CATEGORY' && value.categoryId === source.id) {
      setError('请选择与当前项目 / 专题不同的目标分类。');
      return;
    }

    const payload = toClassificationPayload(value);
    if (!payload?.spaceId || !payload.departmentId || !payload.categoryId) {
      setError('请完整选择空间、部门和项目 / 专题。');
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const request = {
        targetSpaceId: payload.spaceId,
        targetDepartmentId: payload.departmentId,
        targetCategoryId: payload.categoryId,
      };
      if (source.type === 'SPACE') {
        await migrateSpaceDocuments(source.id, request);
      } else {
        await migrateCategoryDocuments(source.id, request);
      }
      onMigrated();
    } catch (caught) {
      setError(errorMessage(caught, '文档迁移失败。'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <form
        aria-label="迁移关联文档"
        aria-modal="true"
        className="modal-panel classification-migration-modal"
        onSubmit={(event) => void handleSubmit(event)}
        role="dialog"
      >
        <div className="toolbar-row compact">
          <div>
            <h3>迁移关联文档</h3>
            <p className="muted">迁移完成后可再次删除原{sourceLabel(source.type)}。</p>
          </div>
          <button className="secondary-button" disabled={busy} onClick={onClose} type="button">
            关闭
          </button>
        </div>

        <div className="migration-source-summary">
          <strong>{source.name}</strong>
          <span>{sourceLabel(source.type)}</span>
          <span>{source.documentCount} 篇关联文档</span>
        </div>

        <KnowledgeClassificationSelect
          allowUnclassified={false}
          disabled={busy}
          idPrefix="classification-document-migration"
          legend="选择目标分类"
          onChange={setValue}
          required
          showValidation
          value={value}
        />

        <p className="muted">
          迁移只会更新文档所属空间、分类部门和项目 / 专题，不会修改文档内容、切片、问答或向量。
        </p>
        {error ? <p className="error">{error}</p> : null}

        <div className="button-row">
          <button disabled={busy} type="submit">
            {busy ? '迁移中' : '确认迁移文档'}
          </button>
          <button className="secondary-button" disabled={busy} onClick={onClose} type="button">
            取消
          </button>
        </div>
      </form>
    </div>
  );
}

function sourceLabel(type: ClassificationMigrationSource['type']) {
  return type === 'SPACE' ? '知识库空间' : '项目 / 专题';
}
