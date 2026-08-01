import { FormEvent, useState } from 'react';

import { errorMessage } from '../../../api/client';
import {
  createImportJob,
  uploadImportJobFile,
  type CreateImportJobPayload,
  type ImportJob,
  type PermissionPayload,
} from '../api/importJobApi';
import {
  KnowledgeClassificationSelect,
  toClassificationPayload,
} from './KnowledgeClassificationSelect';
import { validateClassificationValue } from '../hooks/useKnowledgeClassificationOptions';
import type { KnowledgeClassificationValue } from '../types/classification';

type Props = {
  onUploaded: (job: ImportJob) => void;
};

const MAX_FILE_SIZE = 10 * 1024 * 1024;
const ALLOWED_SUFFIXES = [
  '.md',
  '.markdown',
  '.txt',
  '.csv',
  '.pdf',
  '.docx',
  '.pptx',
  '.xlsx',
  '.png',
  '.jpg',
  '.jpeg',
  '.html',
  '.htm',
];

function emptyClassification(): KnowledgeClassificationValue {
  return { spaceId: null, departmentId: null, categoryId: null };
}

export function DocumentUploadPanel({ onUploaded }: Props) {
  const [allAuthenticated, setAllAuthenticated] = useState(true);
  const [departmentIds, setDepartmentIds] = useState('');
  const [roleIds, setRoleIds] = useState('');
  const [userIds, setUserIds] = useState('');
  const [classificationValue, setClassificationValue] =
    useState<KnowledgeClassificationValue>(() => emptyClassification());
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  function applyFile(next: File | null) {
    setFile(next);
    setError(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) {
      setError('请选择要上传的文档文件。');
      return;
    }
    const validation = validateFile(file);
    if (validation) {
      setError(validation);
      return;
    }
    const classificationValidation = validateClassificationValue(classificationValue, {
      allowUnclassified: true,
    });
    if (classificationValidation) {
      setError(classificationValidation);
      return;
    }
    const permission = buildPermission();
    if (
      !permission.allAuthenticated &&
      !permission.departmentIds?.length &&
      !permission.roleIds?.length &&
      !permission.userIds?.length
    ) {
      setError('至少选择一种访问范围。');
      return;
    }

    setBusy(true);
    setProgress(0);
    setError(null);
    try {
      const importPayload: CreateImportJobPayload = {
        title: file.name.replace(/\.[^.]+$/, '') || file.name,
        permission,
        processingOptions: { enableQaSplit: true, enableEmbedding: true },
      };
      const classification = toClassificationPayload(classificationValue);
      if (classification) {
        importPayload.classification = classification;
      }
      const created = await createImportJob(importPayload);
      const checksum = await checksumFile(file);
      const safeName = file.name.replace(/[^A-Za-z0-9._-]/g, '-');
      const bound = await uploadImportJobFile(created.id, file, {
        objectKey: `uploads/${Date.now()}-${safeName}`,
        checksum,
        onProgress: setProgress,
      });
      onUploaded(bound);
      resetForm();
    } catch (caught) {
      setError(errorMessage(caught, '请求失败。'));
    } finally {
      setBusy(false);
      setProgress(0);
    }
  }

  function resetForm() {
    setAllAuthenticated(true);
    setDepartmentIds('');
    setRoleIds('');
    setUserIds('');
    setClassificationValue(emptyClassification());
    setFile(null);
  }

  function buildPermission(): PermissionPayload {
    return {
      allAuthenticated,
      departmentIds: splitIds(departmentIds),
      roleIds: splitIds(roleIds),
      userIds: splitIds(userIds),
    };
  }

  return (
    <form className="panel upload-panel document-processing-uploader" onSubmit={submit}>
      <div>
        <p className="eyebrow">一键构建解析任务</p>
        <h3>上传源文件</h3>
        <p className="muted">选择文档后，系统会自动创建任务并按默认策略处理。</p>
      </div>

      <label
        className="drop-zone"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          applyFile(event.dataTransfer.files[0] ?? null);
        }}
      >
        <strong>{file ? file.name : '拖拽文件到这里，或点击选择文件'}</strong>
        <span>支持 Markdown、TXT、CSV、PDF、Word、PPT、Excel、图片和 HTML，单文件最大 10MB。</span>
        <input
          accept={ALLOWED_SUFFIXES.join(',')}
          aria-label="选择要解析的文档文件"
          disabled={busy}
          onChange={(event) => applyFile(event.target.files?.[0] ?? null)}
          type="file"
        />
      </label>

      <div className="document-processing-strategy" role="note">
        <strong>默认智能切分策略</strong>
        <span>系统根据文档结构自动切分内容，并生成 QA 问答后写入向量知识库。</span>
      </div>

      <KnowledgeClassificationSelect
        allowUnclassified
        disabled={busy}
        onChange={setClassificationValue}
        showReset={false}
        showValidation
        value={classificationValue}
      />

      <label className="checkbox-row">
        <input
          checked={allAuthenticated}
          disabled={busy}
          id="knowledge-all-authenticated"
          onChange={(event) => setAllAuthenticated(event.target.checked)}
          type="checkbox"
        />
        所有登录用户可访问
      </label>

      <div className="filter-grid document-processing-scope-fields">
        <label>
          部门 ID
          <input
            disabled={allAuthenticated || busy}
            id="knowledge-department-ids"
            onChange={(event) => setDepartmentIds(event.target.value)}
            placeholder="多个 ID 用逗号分隔"
            value={departmentIds}
          />
        </label>
        <label>
          角色 ID
          <input
            disabled={allAuthenticated || busy}
            id="knowledge-role-ids"
            onChange={(event) => setRoleIds(event.target.value)}
            placeholder="多个 ID 用逗号分隔"
            value={roleIds}
          />
        </label>
        <label>
          用户 ID
          <input
            disabled={allAuthenticated || busy}
            id="knowledge-user-ids"
            onChange={(event) => setUserIds(event.target.value)}
            placeholder="多个 ID 用逗号分隔"
            value={userIds}
          />
        </label>
      </div>

      <button className="document-processing-submit" disabled={busy} id="document-processing-submit" type="submit">
        {busy ? '正在构建解析任务…' : '▷ 一键构建解析任务'}
      </button>
      {busy ? (
        <div aria-live="polite" className="upload-progress">
          <div className="progress-bar">
            <i style={{ width: `${progress}%` }} />
          </div>
          <span className="muted">上传 {progress}%</span>
        </div>
      ) : null}
      {error ? <p className="error" role="alert">{error}</p> : null}
    </form>
  );
}

function validateFile(file: File) {
  const lowerName = file.name.toLowerCase();
  if (!ALLOWED_SUFFIXES.some((suffix) => lowerName.endsWith(suffix))) {
    return `当前支持的文件类型：${ALLOWED_SUFFIXES.join('、')}。`;
  }
  if (file.size > MAX_FILE_SIZE) {
    return '文件超过 10MB 限制。';
  }
  return null;
}

function splitIds(value: string) {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

async function checksumFile(file: File) {
  const data = await file.arrayBuffer();
  const digest = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(digest))
    .map((item) => item.toString(16).padStart(2, '0'))
    .join('');
}
