/* eslint-disable react-refresh/only-export-components */
import type {
  KnowledgeClassificationPath,
  KnowledgeClassificationSelectProps,
  KnowledgeClassificationValue,
  UpdateDocumentClassificationPayload,
} from '../types/classification';
import {
  useKnowledgeClassificationOptions,
  validateClassificationValue,
} from '../hooks/useKnowledgeClassificationOptions';

export function KnowledgeClassificationSelect({
  value,
  defaultValue,
  onChange,
  required = false,
  allowUnclassified = true,
  disabled = false,
  className = '',
  idPrefix = 'knowledge-classification',
  legend = '知识库分类',
  showReset = true,
  showValidation = required,
}: KnowledgeClassificationSelectProps) {
  const selection = useKnowledgeClassificationOptions(value ?? defaultValue, {
    disabled,
    required,
    allowUnclassified,
  });
  const validationError = validateClassificationValue(selection.value, {
    required,
    allowUnclassified,
  });
  const shouldRequireFullPath = required || !allowUnclassified;
  const showError = showValidation && Boolean(validationError);
  const rootClassName = ['classification-select', className].filter(Boolean).join(' ');
  const initialPath = (value ?? defaultValue) as
    Partial<KnowledgeClassificationPath> | null | undefined;

  function emit(nextValue: KnowledgeClassificationValue) {
    onChange?.(nextValue, toClassificationPayload(nextValue));
  }

  function handleSpaceChange(nextSpaceId: string) {
    const nextValue = selection.setSpaceId(nextSpaceId);
    emit(nextValue);
  }

  function handleDepartmentChange(nextDepartmentId: string) {
    const nextValue = selection.setDepartmentId(nextDepartmentId);
    emit(nextValue);
  }

  function handleCategoryChange(nextCategoryId: string) {
    const nextValue = selection.setCategoryId(nextCategoryId);
    emit(nextValue);
  }

  function handleReset() {
    const nextValue = selection.resetClassification();
    emit(nextValue);
  }

  return (
    <fieldset className={rootClassName} disabled={disabled}>
      {legend ? <legend>{legend}</legend> : null}
      <div className="filter-grid">
        <label htmlFor={`${idPrefix}-space`}>
          知识库空间
          <select
            aria-invalid={showError && !selection.value.spaceId}
            id={`${idPrefix}-space`}
            onChange={(event) => handleSpaceChange(event.target.value)}
            required={shouldRequireFullPath}
            value={selection.value.spaceId ?? ''}
          >
            <option value="">{allowUnclassified ? '未分类 / 请选择空间' : '请选择空间'}</option>
            {renderMissingSelectedOption(
              selection.value.spaceId,
              initialPath?.spaceName,
              selection.spaces.some((space) => space.id === selection.value.spaceId),
            )}
            {selection.spaces.map((space) => (
              <option key={space.id} value={space.id}>
                {space.name}
              </option>
            ))}
          </select>
        </label>

        <label htmlFor={`${idPrefix}-department`}>
          分类部门
          <select
            aria-invalid={showError && !selection.value.departmentId}
            disabled={!selection.value.spaceId || selection.loading.departments}
            id={`${idPrefix}-department`}
            onChange={(event) => handleDepartmentChange(event.target.value)}
            required={shouldRequireFullPath}
            value={selection.value.departmentId ?? ''}
          >
            <option value="">请选择部门</option>
            {renderMissingSelectedOption(
              selection.value.departmentId,
              initialPath?.departmentName ?? initialPath?.classificationDepartmentName,
              selection.departments.some(
                (department) => department.id === selection.value.departmentId,
              ),
            )}
            {selection.departments.map((department) => (
              <option key={department.id} value={department.id}>
                {department.name}
              </option>
            ))}
          </select>
        </label>

        <label htmlFor={`${idPrefix}-category`}>
          项目 / 专题
          <select
            aria-invalid={showError && !selection.value.categoryId}
            disabled={
              !selection.value.spaceId ||
              !selection.value.departmentId ||
              selection.loading.categories
            }
            id={`${idPrefix}-category`}
            onChange={(event) => handleCategoryChange(event.target.value)}
            required={shouldRequireFullPath}
            value={selection.value.categoryId ?? ''}
          >
            <option value="">请选择项目 / 专题</option>
            {renderMissingSelectedOption(
              selection.value.categoryId,
              initialPath?.categoryName,
              selection.categories.some((category) => category.id === selection.value.categoryId),
            )}
            {selection.categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {showReset && !required && allowUnclassified ? (
        <div className="button-row">
          <button disabled={selection.isUnclassified} onClick={handleReset} type="button">
            清空分类
          </button>
        </div>
      ) : null}

      <ClassificationStatus
        empty={selection.empty.spaces}
        error={selection.errors.spaces}
        loading={selection.loading.spaces}
        loadingText="正在加载知识库空间..."
        emptyText="暂无可用知识库空间。"
        onRetry={() => void selection.loadSpaces()}
      />
      <ClassificationStatus
        empty={selection.empty.departments}
        error={selection.errors.departments}
        loading={selection.loading.departments}
        loadingText="正在加载部门..."
        emptyText="暂无可用部门。"
        onRetry={() => void selection.loadDepartments()}
      />
      {selection.value.spaceId && selection.value.departmentId ? (
        <ClassificationStatus
          empty={selection.empty.categories}
          error={selection.errors.categories}
          loading={selection.loading.categories}
          loadingText="正在加载项目 / 专题..."
          emptyText="该空间和部门下暂无项目 / 专题。"
          onRetry={() =>
            void selection.loadCategories(selection.value.spaceId, selection.value.departmentId)
          }
        />
      ) : (
        <p className="muted">请选择空间和部门后加载项目 / 专题。</p>
      )}
      {showError ? <p className="error">{validationError}</p> : null}
    </fieldset>
  );
}

export function toClassificationPayload(
  value: KnowledgeClassificationValue | KnowledgeClassificationPath | null | undefined,
): UpdateDocumentClassificationPayload | null {
  const spaceId = normalizeId(value?.spaceId);
  const departmentId = normalizeId(value?.departmentId);
  const categoryId = normalizeId(value?.categoryId);
  if (!spaceId && !departmentId && !categoryId) {
    return null;
  }
  return { spaceId, departmentId, categoryId };
}

export function formatClassificationPath(
  value: KnowledgeClassificationPath | KnowledgeClassificationValue | null | undefined,
  fallback = '未分类',
) {
  if (!value) {
    return fallback;
  }
  const pathValue = value as Partial<KnowledgeClassificationPath>;
  const parts = [
    pathValue.spaceName || value.spaceId,
    pathValue.departmentName || pathValue.classificationDepartmentName || value.departmentId,
    pathValue.categoryName || value.categoryId,
  ].filter(Boolean);
  return parts.length ? parts.join(' / ') : fallback;
}

function renderMissingSelectedOption(
  selectedId: string | null,
  label: string | null | undefined,
  exists: boolean,
) {
  if (!selectedId || exists) {
    return null;
  }
  return (
    <option key={selectedId} value={selectedId}>
      {label || selectedId}
    </option>
  );
}

type ClassificationStatusProps = {
  loading: boolean;
  error: string | null;
  empty: boolean;
  loadingText: string;
  emptyText: string;
  onRetry: () => void;
};

function ClassificationStatus({
  loading,
  error,
  empty,
  loadingText,
  emptyText,
  onRetry,
}: ClassificationStatusProps) {
  if (loading) {
    return <p className="muted">{loadingText}</p>;
  }
  if (error) {
    return (
      <div className="error-box">
        <span>{error}</span>
        <button onClick={onRetry} type="button">
          重试
        </button>
      </div>
    );
  }
  if (empty) {
    return <p className="muted">{emptyText}</p>;
  }
  return null;
}

function normalizeId(value: string | null | undefined) {
  const trimmed = value?.trim();
  return trimmed || null;
}
