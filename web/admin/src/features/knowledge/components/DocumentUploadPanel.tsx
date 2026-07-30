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
function emptyClassification(): KnowledgeClassificationValue {
  return {
    spaceId: null,
    departmentId: null,
    categoryId: null,
  };
}

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

export function DocumentUploadPanel({ onUploaded }: Props) {
  const [title, setTitle] = useState('');
  const [titleEdited, setTitleEdited] = useState(false);
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
    // 自动把文件名（去扩展名）填入标题；用户手动改过标题则不覆盖
    if (next && !titleEdited) {
      setTitle(next.name.replace(/\.[^.]+$/, ''));
    }
  }

  function handleTitleChange(value: string) {
    setTitle(value);
    // 清空标题视为放弃手动输入，下次选文件时恢复自动填充
    setTitleEdited(value.trim() !== '');
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
        title: title.trim() || file.name,
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

  function handleClassificationChange(value: KnowledgeClassificationValue) {
    setClassificationValue(value);
  }

  function resetForm() {
    setTitle('');
    setTitleEdited(false);
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
    <form className="panel upload-panel" onSubmit={submit}>
      <div>
        <h3>上传文档</h3>
        <p className="muted">
          支持 Markdown、TXT、CSV，以及 PDF、Word、PPT、Excel、图片、HTML（需服务端配置 MinerU 或
          Docling 解析服务）。上传后自动进入解析、QA 拆分和向量化链路。
        </p>
      </div>
      <label>
        文档标题
        <input
          onChange={(event) => handleTitleChange(event.target.value)}
          placeholder="留空则自动使用上传文件名"
          value={title}
        />
      </label>
      <label
        className="drop-zone"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          applyFile(event.dataTransfer.files[0] ?? null);
        }}
      >
        <span>{file ? file.name : '拖拽文件到这里，或点击选择文件'}</span>
        <input
          accept={ALLOWED_SUFFIXES.join(',')}
          onChange={(event) => applyFile(event.target.files?.[0] ?? null)}
          type="file"
        />
      </label>
      <KnowledgeClassificationSelect
        allowUnclassified
        disabled={busy}
        onChange={handleClassificationChange}
        showReset={false}
        showValidation
        value={classificationValue}
      />
      <label className="checkbox-row">
        <input
          checked={allAuthenticated}
          onChange={(event) => setAllAuthenticated(event.target.checked)}
          type="checkbox"
        />
        所有登录用户可访问
      </label>
      <div className="filter-grid">
        <label>
          部门 ID
          <input
            disabled={allAuthenticated}
            onChange={(event) => setDepartmentIds(event.target.value)}
            placeholder="多个 ID 用逗号分隔"
            value={departmentIds}
          />
        </label>
        <label>
          角色 ID
          <input
            disabled={allAuthenticated}
            onChange={(event) => setRoleIds(event.target.value)}
            placeholder="多个 ID 用逗号分隔"
            value={roleIds}
          />
        </label>
        <label>
          用户 ID
          <input
            disabled={allAuthenticated}
            onChange={(event) => setUserIds(event.target.value)}
            placeholder="多个 ID 用逗号分隔"
            value={userIds}
          />
        </label>
      </div>
      <button disabled={busy} type="submit">
        {busy ? '提交中' : '创建导入任务'}
      </button>
      {busy ? (
        <div className="upload-progress">
          <div className="progress-bar">
            <i style={{ width: `${progress}%` }} />
          </div>
          <span className="muted">{progress}%</span>
        </div>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
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
  return `sha256:${Array.from(new Uint8Array(digest))
    .map((item) => item.toString(16).padStart(2, '0'))
    .join('')}`;
}
