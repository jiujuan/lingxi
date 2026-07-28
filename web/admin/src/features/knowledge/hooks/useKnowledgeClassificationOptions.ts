import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { errorMessage } from '../../../api/client';
import { listDepartments } from '../../org/api/orgApi';
import type { Department } from '../../org/types';
import { listKnowledgeCategories, listKnowledgeSpaces } from '../api/classificationApi';
import type {
  KnowledgeCategory,
  KnowledgeClassificationPath,
  KnowledgeClassificationValue,
  KnowledgeSpace,
} from '../types/classification';

type LoadKey = 'spaces' | 'departments' | 'categories';

export type KnowledgeClassificationLoadingState = Record<LoadKey, boolean>;
export type KnowledgeClassificationErrorState = Record<LoadKey, string | null>;
export type KnowledgeClassificationEmptyState = Record<LoadKey, boolean>;

export type UseKnowledgeClassificationOptionsConfig = {
  disabled?: boolean;
  autoLoad?: boolean;
  required?: boolean;
  allowUnclassified?: boolean;
};

const EMPTY_VALUE: KnowledgeClassificationValue = {
  spaceId: null,
  departmentId: null,
  categoryId: null,
};

const INITIAL_LOADING: KnowledgeClassificationLoadingState = {
  spaces: false,
  departments: false,
  categories: false,
};

const INITIAL_ERRORS: KnowledgeClassificationErrorState = {
  spaces: null,
  departments: null,
  categories: null,
};

/**
 * Loads and coordinates the knowledge classification cascade:
 * knowledge space -> classification department -> project/topic category.
 */
export function useKnowledgeClassificationOptions(
  initialValue?: KnowledgeClassificationValue | KnowledgeClassificationPath | null,
  options: UseKnowledgeClassificationOptionsConfig = {},
) {
  const { disabled = false, autoLoad = true, required = false, allowUnclassified = true } = options;
  const [value, setValue] = useState<KnowledgeClassificationValue>(() =>
    normalizeValue(initialValue),
  );
  const [spaces, setSpaces] = useState<KnowledgeSpace[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [categories, setCategories] = useState<KnowledgeCategory[]>([]);
  const [loading, setLoading] = useState<KnowledgeClassificationLoadingState>(INITIAL_LOADING);
  const [errors, setErrors] = useState<KnowledgeClassificationErrorState>(INITIAL_ERRORS);
  const categoryLoadSeq = useRef(0);

  useEffect(() => {
    setValue((current) => {
      const next = normalizeValue(initialValue);
      return isSameValue(current, next) ? current : next;
    });
  }, [initialValue]);

  const setLoadingKey = useCallback((key: LoadKey, next: boolean) => {
    setLoading((current) => ({ ...current, [key]: next }));
  }, []);

  const setErrorKey = useCallback((key: LoadKey, next: string | null) => {
    setErrors((current) => ({ ...current, [key]: next }));
  }, []);

  const loadSpaces = useCallback(async () => {
    if (disabled) {
      return [];
    }
    setLoadingKey('spaces', true);
    setErrorKey('spaces', null);
    try {
      const result = await listKnowledgeSpaces();
      setSpaces(result.data);
      return result.data;
    } catch (caught) {
      setSpaces([]);
      setErrorKey('spaces', errorMessage(caught, '知识库空间加载失败'));
      return [];
    } finally {
      setLoadingKey('spaces', false);
    }
  }, [disabled, setErrorKey, setLoadingKey]);

  const loadDepartments = useCallback(async () => {
    if (disabled) {
      return [];
    }
    setLoadingKey('departments', true);
    setErrorKey('departments', null);
    try {
      const result = await listDepartments();
      setDepartments(result.data);
      return result.data;
    } catch (caught) {
      setDepartments([]);
      setErrorKey('departments', errorMessage(caught, '部门加载失败'));
      return [];
    } finally {
      setLoadingKey('departments', false);
    }
  }, [disabled, setErrorKey, setLoadingKey]);

  const loadCategories = useCallback(
    async (spaceId: string | null | undefined, departmentId: string | null | undefined) => {
      const normalizedSpaceId = normalizeId(spaceId);
      const normalizedDepartmentId = normalizeId(departmentId);
      const seq = categoryLoadSeq.current + 1;
      categoryLoadSeq.current = seq;

      if (disabled || !normalizedSpaceId || !normalizedDepartmentId) {
        setCategories([]);
        setErrorKey('categories', null);
        setLoadingKey('categories', false);
        return [];
      }

      setLoadingKey('categories', true);
      setErrorKey('categories', null);
      try {
        const result = await listKnowledgeCategories({
          spaceId: normalizedSpaceId,
          departmentId: normalizedDepartmentId,
        });
        if (categoryLoadSeq.current === seq) {
          setCategories(result.data);
        }
        return result.data;
      } catch (caught) {
        if (categoryLoadSeq.current === seq) {
          setCategories([]);
          setErrorKey('categories', errorMessage(caught, '项目 / 专题加载失败'));
        }
        return [];
      } finally {
        if (categoryLoadSeq.current === seq) {
          setLoadingKey('categories', false);
        }
      }
    },
    [disabled, setErrorKey, setLoadingKey],
  );

  const setSpaceId = useCallback(
    (spaceId: string | null) => {
      const next: KnowledgeClassificationValue = {
        spaceId: normalizeId(spaceId),
        departmentId: null,
        categoryId: null,
      };
      categoryLoadSeq.current += 1;
      setCategories([]);
      setErrorKey('categories', null);
      setValue(next);
      return next;
    },
    [setErrorKey],
  );

  const setDepartmentId = useCallback(
    (departmentId: string | null) => {
      const next: KnowledgeClassificationValue = {
        spaceId: value.spaceId,
        departmentId: normalizeId(departmentId),
        categoryId: null,
      };
      categoryLoadSeq.current += 1;
      setCategories([]);
      setErrorKey('categories', null);
      setValue(next);
      return next;
    },
    [setErrorKey, value.spaceId],
  );

  const setCategoryId = useCallback(
    (categoryId: string | null) => {
      const next: KnowledgeClassificationValue = {
        ...value,
        categoryId: normalizeId(categoryId),
      };
      setValue(next);
      return next;
    },
    [value],
  );

  const resetClassification = useCallback(() => {
    categoryLoadSeq.current += 1;
    setCategories([]);
    setErrorKey('categories', null);
    setValue(EMPTY_VALUE);
    return EMPTY_VALUE;
  }, [setErrorKey]);

  useEffect(() => {
    if (!autoLoad) {
      return;
    }
    void loadSpaces();
    void loadDepartments();
  }, [autoLoad, loadDepartments, loadSpaces]);

  useEffect(() => {
    if (!autoLoad) {
      return;
    }
    void loadCategories(value.spaceId, value.departmentId);
  }, [autoLoad, loadCategories, value.departmentId, value.spaceId]);

  const empty = useMemo<KnowledgeClassificationEmptyState>(
    () => ({
      spaces: !loading.spaces && !errors.spaces && spaces.length === 0,
      departments: !loading.departments && !errors.departments && departments.length === 0,
      categories:
        Boolean(value.spaceId && value.departmentId) &&
        !loading.categories &&
        !errors.categories &&
        categories.length === 0,
    }),
    [
      categories.length,
      departments.length,
      errors,
      loading,
      spaces.length,
      value.departmentId,
      value.spaceId,
    ],
  );

  const validationError = validateClassificationValue(value, { required, allowUnclassified });

  return {
    value,
    spaces,
    departments,
    categories,
    loading,
    errors,
    empty,
    disabled,
    isComplete: Boolean(value.spaceId && value.departmentId && value.categoryId),
    isUnclassified: !value.spaceId && !value.departmentId && !value.categoryId,
    validationError,
    loadSpaces,
    loadDepartments,
    loadCategories,
    setSpaceId,
    setDepartmentId,
    setCategoryId,
    resetClassification,
  };
}

export function normalizeValue(
  value?: KnowledgeClassificationValue | KnowledgeClassificationPath | null,
): KnowledgeClassificationValue {
  return {
    spaceId: normalizeId(value?.spaceId),
    departmentId: normalizeId(value?.departmentId),
    categoryId: normalizeId(value?.categoryId),
  };
}

export function validateClassificationValue(
  value: KnowledgeClassificationValue,
  options: { required?: boolean; allowUnclassified?: boolean } = {},
) {
  const { required = false, allowUnclassified = true } = options;
  const selectedCount = [value.spaceId, value.departmentId, value.categoryId].filter(
    Boolean,
  ).length;
  if (selectedCount === 3) {
    return null;
  }
  if (selectedCount === 0 && allowUnclassified && !required) {
    return null;
  }
  if (selectedCount === 0) {
    return '请选择知识库分类。';
  }
  return '请完整选择空间、部门和项目 / 专题。';
}

function normalizeId(value: string | null | undefined) {
  const trimmed = value?.trim();
  return trimmed || null;
}

function isSameValue(left: KnowledgeClassificationValue, right: KnowledgeClassificationValue) {
  return (
    left.spaceId === right.spaceId &&
    left.departmentId === right.departmentId &&
    left.categoryId === right.categoryId
  );
}
