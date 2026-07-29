import { useCallback, useEffect, useMemo, useState } from 'react';

import { errorMessage } from '../../../api/client';
import { hasPermission } from '../../../auth/authStore';
import { formatDateTime } from '../../../shared/format';
import { listDepartments } from '../../org/api/orgApi';
import type { Department } from '../../org/types';
import {
  createKnowledgeCategory,
  createKnowledgeSpace,
  deleteKnowledgeCategory,
  deleteKnowledgeSpace,
  listKnowledgeCategories,
  listKnowledgeCategoryStats,
  listKnowledgeSpaces,
  listKnowledgeSpaceStats,
  updateKnowledgeCategory,
  updateKnowledgeSpace,
} from '../api/classificationApi';
import { KnowledgeCategoryModal } from '../components/KnowledgeCategoryModal';
import { KnowledgeSpaceModal } from '../components/KnowledgeSpaceModal';
import type {
  CreateKnowledgeCategoryPayload,
  CreateKnowledgeSpacePayload,
  KnowledgeCategory,
  KnowledgeCategoryStats,
  KnowledgeClassificationStats,
  KnowledgeSpace,
  KnowledgeSpaceStats,
  UpdateKnowledgeCategoryPayload,
  UpdateKnowledgeSpacePayload,
} from '../types/classification';

export function KnowledgeClassificationPage() {
  const canWrite = hasPermission('DOCUMENT_WRITE');
  const [spaces, setSpaces] = useState<KnowledgeSpace[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [categories, setCategories] = useState<KnowledgeCategory[]>([]);
  const [spaceStats, setSpaceStats] = useState<KnowledgeSpaceStats[]>([]);
  const [spaceStatsSummary, setSpaceStatsSummary] = useState<KnowledgeClassificationStats | null>(
    null,
  );
  const [categoryStats, setCategoryStats] = useState<KnowledgeCategoryStats[]>([]);
  const [categoryUnclassifiedStats, setCategoryUnclassifiedStats] =
    useState<KnowledgeClassificationStats | null>(null);
  const [selectedSpaceId, setSelectedSpaceId] = useState('');
  const [selectedDepartmentId, setSelectedDepartmentId] = useState('');
  const [spacesLoading, setSpacesLoading] = useState(false);
  const [departmentsLoading, setDepartmentsLoading] = useState(false);
  const [categoriesLoading, setCategoriesLoading] = useState(false);
  const [spaceStatsLoading, setSpaceStatsLoading] = useState(false);
  const [categoryStatsLoading, setCategoryStatsLoading] = useState(false);
  const [spacesError, setSpacesError] = useState<string | null>(null);
  const [departmentsError, setDepartmentsError] = useState<string | null>(null);
  const [categoriesError, setCategoriesError] = useState<string | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editingSpace, setEditingSpace] = useState<KnowledgeSpace | null>(null);
  const [showSpaceModal, setShowSpaceModal] = useState(false);
  const [editingCategory, setEditingCategory] = useState<KnowledgeCategory | null>(null);
  const [showCategoryModal, setShowCategoryModal] = useState(false);

  const departmentById = useMemo(
    () => new Map(departments.map((department) => [department.id, department])),
    [departments],
  );
  const spaceStatsById = useMemo(
    () => new Map(spaceStats.map((item) => [item.spaceId, item])),
    [spaceStats],
  );
  const categoryStatsById = useMemo(
    () => new Map(categoryStats.map((item) => [item.categoryId, item])),
    [categoryStats],
  );
  const selectedSpace = spaces.find((space) => space.id === selectedSpaceId) ?? null;
  const selectedDepartment = departmentById.get(selectedDepartmentId) ?? null;

  const loadSpaces = useCallback(async () => {
    setSpacesLoading(true);
    setSpacesError(null);
    try {
      const result = await listKnowledgeSpaces();
      setSpaces(result.data);
      setSelectedSpaceId((current) =>
        current && result.data.some((space) => space.id === current)
          ? current
          : (result.data[0]?.id ?? ''),
      );
    } catch (caught) {
      setSpaces([]);
      setSpacesError(errorMessage(caught, '知识库空间加载失败。'));
    } finally {
      setSpacesLoading(false);
    }
  }, []);

  const loadSpaceStats = useCallback(async () => {
    setSpaceStatsLoading(true);
    setStatsError(null);
    try {
      const result = await listKnowledgeSpaceStats();
      setSpaceStats(result.data);
      setSpaceStatsSummary(result.summary);
    } catch (caught) {
      setSpaceStats([]);
      setSpaceStatsSummary(null);
      setStatsError(errorMessage(caught, '分类统计加载失败。'));
    } finally {
      setSpaceStatsLoading(false);
    }
  }, []);

  const loadDepartments = useCallback(async () => {
    setDepartmentsLoading(true);
    setDepartmentsError(null);
    try {
      const result = await listDepartments();
      setDepartments(result.data);
      setSelectedDepartmentId((current) =>
        current && result.data.some((department) => department.id === current)
          ? current
          : (result.data[0]?.id ?? ''),
      );
    } catch (caught) {
      setDepartments([]);
      setDepartmentsError(errorMessage(caught, '部门加载失败。'));
    } finally {
      setDepartmentsLoading(false);
    }
  }, []);

  const loadCategories = useCallback(
    async (spaceId = selectedSpaceId, departmentId = selectedDepartmentId) => {
      if (!spaceId || !departmentId) {
        setCategories([]);
        setCategoriesError(null);
        return;
      }
      setCategoriesLoading(true);
      setCategoriesError(null);
      try {
        const result = await listKnowledgeCategories({
          spaceId,
          departmentId,
        });
        setCategories(result.data);
      } catch (caught) {
        setCategories([]);
        setCategoriesError(errorMessage(caught, '项目 / 专题加载失败。'));
      } finally {
        setCategoriesLoading(false);
      }
    },
    [selectedDepartmentId, selectedSpaceId],
  );

  const loadCategoryStats = useCallback(
    async (spaceId = selectedSpaceId, departmentId = selectedDepartmentId) => {
      if (!spaceId || !departmentId) {
        setCategoryStats([]);
        setCategoryUnclassifiedStats(null);
        return;
      }
      setCategoryStatsLoading(true);
      setStatsError(null);
      try {
        const result = await listKnowledgeCategoryStats({
          spaceId,
          departmentId,
        });
        setCategoryStats(result.data);
        setCategoryUnclassifiedStats(result.unclassified);
      } catch (caught) {
        setCategoryStats([]);
        setCategoryUnclassifiedStats(null);
        setStatsError(errorMessage(caught, '分类统计加载失败。'));
      } finally {
        setCategoryStatsLoading(false);
      }
    },
    [selectedDepartmentId, selectedSpaceId],
  );

  useEffect(() => {
    void loadSpaces();
    void loadDepartments();
    void loadSpaceStats();
  }, [loadDepartments, loadSpaceStats, loadSpaces]);

  useEffect(() => {
    void loadCategories();
    void loadCategoryStats();
  }, [loadCategories, loadCategoryStats]);

  function openCreateSpace() {
    setEditingSpace(null);
    setShowSpaceModal(true);
  }

  function openEditSpace(space: KnowledgeSpace) {
    setEditingSpace(space);
    setShowSpaceModal(true);
  }

  function openCreateCategory() {
    setEditingCategory(null);
    setShowCategoryModal(true);
  }

  function openEditCategory(category: KnowledgeCategory) {
    setEditingCategory(category);
    setShowCategoryModal(true);
  }

  async function handleCreateSpace(payload: CreateKnowledgeSpacePayload) {
    await createKnowledgeSpace(payload);
    setNotice('知识库空间已创建。');
    await Promise.all([loadSpaces(), loadSpaceStats()]);
  }

  async function handleUpdateSpace(spaceId: string, payload: UpdateKnowledgeSpacePayload) {
    await updateKnowledgeSpace(spaceId, payload);
    setNotice('知识库空间已更新。');
    await Promise.all([loadSpaces(), loadSpaceStats(), loadCategoryStats()]);
  }

  async function handleDeleteSpace(space: KnowledgeSpace) {
    if (!window.confirm(`确认删除知识库空间「${space.name}」？`)) {
      return;
    }
    setNotice(null);
    setSpacesError(null);
    try {
      await deleteKnowledgeSpace(space.id);
      setNotice('知识库空间已删除。');
      await Promise.all([loadSpaces(), loadSpaceStats(), loadCategoryStats()]);
      if (space.id === selectedSpaceId) {
        setCategories([]);
        setCategoryStats([]);
        setCategoryUnclassifiedStats(null);
      }
    } catch (caught) {
      setSpacesError(errorMessage(caught, '知识库空间删除失败。'));
    }
  }

  async function handleSubmitSpace(
    payload: CreateKnowledgeSpacePayload | UpdateKnowledgeSpacePayload,
  ) {
    if (editingSpace) {
      await handleUpdateSpace(editingSpace.id, payload as UpdateKnowledgeSpacePayload);
    } else {
      await handleCreateSpace(payload as CreateKnowledgeSpacePayload);
    }
  }

  async function handleCreateCategory(payload: CreateKnowledgeCategoryPayload) {
    await createKnowledgeCategory(payload);
    setNotice('项目 / 专题已创建。');
    if (payload.spaceId !== selectedSpaceId) {
      setSelectedSpaceId(payload.spaceId);
    }
    if (payload.departmentId !== selectedDepartmentId) {
      setSelectedDepartmentId(payload.departmentId);
    }
    await Promise.all([
      loadCategories(payload.spaceId, payload.departmentId),
      loadCategoryStats(payload.spaceId, payload.departmentId),
      loadSpaceStats(),
    ]);
  }

  async function handleUpdateCategory(categoryId: string, payload: UpdateKnowledgeCategoryPayload) {
    await updateKnowledgeCategory(categoryId, payload);
    setNotice('项目 / 专题已更新。');
    const nextSpaceId = payload.spaceId || selectedSpaceId;
    const nextDepartmentId = payload.departmentId || selectedDepartmentId;
    if (payload.spaceId && payload.spaceId !== selectedSpaceId) {
      setSelectedSpaceId(payload.spaceId);
    }
    if (payload.departmentId && payload.departmentId !== selectedDepartmentId) {
      setSelectedDepartmentId(payload.departmentId);
    }
    await Promise.all([
      loadCategories(nextSpaceId, nextDepartmentId),
      loadCategoryStats(nextSpaceId, nextDepartmentId),
      loadSpaceStats(),
    ]);
  }

  async function handleDeleteCategory(category: KnowledgeCategory) {
    if (!window.confirm(`确认删除项目 / 专题「${category.name}」？`)) {
      return;
    }
    setNotice(null);
    setCategoriesError(null);
    try {
      await deleteKnowledgeCategory(category.id);
      setNotice('项目 / 专题已删除。');
      await Promise.all([loadCategories(), loadCategoryStats(), loadSpaceStats()]);
    } catch (caught) {
      setCategoriesError(errorMessage(caught, '项目 / 专题删除失败。'));
    }
  }

  async function handleSubmitCategory(
    payload: CreateKnowledgeCategoryPayload | UpdateKnowledgeCategoryPayload,
  ) {
    if (editingCategory) {
      await handleUpdateCategory(editingCategory.id, payload as UpdateKnowledgeCategoryPayload);
    } else {
      await handleCreateCategory(payload as CreateKnowledgeCategoryPayload);
    }
  }

  return (
    <div className="page-stack">
      <section className="toolbar-row">
        <div>
          <p className="eyebrow">知识库中心</p>
          <h2>知识库分类</h2>
        </div>
        <div className="toolbar-actions">
          <a className="secondary-link" href="#knowledge">
            返回知识库中心
          </a>
          {canWrite ? (
            <button onClick={openCreateSpace} type="button">
              新建空间
            </button>
          ) : null}
        </div>
      </section>

      {notice ? <div className="status-pill">{notice}</div> : null}

      <section className="classification-admin-grid">
        <section className="panel">
          <div className="toolbar-row compact">
            <div>
              <h3>知识库空间</h3>
              <p className="muted">管理分类的第一层空间。</p>
            </div>
            <button
              className="secondary-button"
              onClick={() => {
                void loadSpaces();
                void loadSpaceStats();
              }}
              type="button"
            >
              重试 / 刷新
            </button>
          </div>
          {spacesError ? <div className="error-box">{spacesError}</div> : null}
          {statsError ? <div className="error-box">{statsError}</div> : null}
          {spacesLoading ? <p className="muted">正在加载知识库空间...</p> : null}
          {spaceStatsLoading ? <p className="muted">正在加载空间统计...</p> : null}
          <p className="classification-stats-summary">
            全局未分类：{formatClassificationStats(spaceStatsSummary)}
          </p>
          {!spacesLoading && !spaces.length ? (
            <div className="empty-state">
              <strong>暂无知识库空间</strong>
              <p>点击「新建空间」创建第一个知识库空间。</p>
            </div>
          ) : null}
          <div className="table-list">
            {spaces.map((space) => (
              <div className="table-row classification-space-row" key={space.id}>
                <button
                  className="link-button title-button"
                  onClick={() => setSelectedSpaceId(space.id)}
                  type="button"
                >
                  <strong>{space.name}</strong>
                  <span>
                    {space.id === selectedSpaceId ? '当前筛选空间' : '点击筛选项目 / 专题'}
                  </span>
                </button>
                <code>{space.code}</code>
                <span>{space.description || '-'}</span>
                <span className="classification-stats">
                  {formatClassificationStats(spaceStatsById.get(space.id))}
                </span>
                <span>
                  {statusLabel(space.status)} · 排序 {space.sortOrder}
                </span>
                <span>{formatDateTime(space.updatedAt || space.createdAt)}</span>
                {canWrite ? (
                  <div className="button-row">
                    <button
                      className="secondary-button"
                      onClick={() => openEditSpace(space)}
                      type="button"
                    >
                      编辑
                    </button>
                    <button
                      className="danger-button"
                      onClick={() => void handleDeleteSpace(space)}
                      type="button"
                    >
                      删除
                    </button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="toolbar-row compact">
            <div>
              <h3>项目 / 专题</h3>
              <p className="muted">按空间 + 分类部门维护第二阶段分类。</p>
            </div>
            {canWrite ? (
              <button
                disabled={!selectedSpaceId || !selectedDepartmentId}
                onClick={openCreateCategory}
                type="button"
              >
                新建项目 / 专题
              </button>
            ) : null}
          </div>

          <div className="filter-grid">
            <label>
              知识库空间
              <select
                disabled={spacesLoading}
                onChange={(event) => setSelectedSpaceId(event.target.value)}
                value={selectedSpaceId}
              >
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
                disabled={departmentsLoading}
                onChange={(event) => setSelectedDepartmentId(event.target.value)}
                value={selectedDepartmentId}
              >
                <option value="">请选择部门</option>
                {departments.map((department) => (
                  <option key={department.id} value={department.id}>
                    {department.name}（{department.code}）
                  </option>
                ))}
              </select>
            </label>
            <button
              className="secondary-button"
              disabled={!selectedSpaceId || !selectedDepartmentId}
              onClick={() => {
                void loadCategories();
                void loadCategoryStats();
              }}
              type="button"
            >
              刷新项目 / 专题
            </button>
          </div>

          {departmentsError ? <div className="error-box">{departmentsError}</div> : null}
          {categoriesError ? <div className="error-box">{categoriesError}</div> : null}
          {departmentsLoading ? <p className="muted">正在加载部门...</p> : null}
          {categoriesLoading ? <p className="muted">正在加载项目 / 专题...</p> : null}
          {categoryStatsLoading ? <p className="muted">正在加载项目 / 专题统计...</p> : null}
          {selectedSpaceId && selectedDepartmentId ? (
            <p className="classification-stats-summary">
              当前范围未分类：{formatClassificationStats(categoryUnclassifiedStats)}
            </p>
          ) : null}
          {!selectedSpaceId || !selectedDepartmentId ? (
            <div className="empty-state">
              <strong>请选择空间和分类部门</strong>
              <p>选择后会从后端加载该路径下的项目 / 专题。</p>
            </div>
          ) : null}
          {selectedSpaceId && selectedDepartmentId && !categoriesLoading && !categories.length ? (
            <div className="empty-state">
              <strong>暂无项目 / 专题</strong>
              <p>
                当前筛选：{selectedSpace?.name || selectedSpaceId} /{' '}
                {selectedDepartment?.name || selectedDepartmentId}。
              </p>
            </div>
          ) : null}

          <div className="table-list">
            {categories.map((category) => (
              <div className="table-row classification-category-row" key={category.id}>
                <strong>{category.name}</strong>
                <code>{category.code}</code>
                <span>{categoryTypeLabel(category.categoryType)}</span>
                <span className="classification-stats">
                  {formatClassificationStats(categoryStatsById.get(category.id))}
                </span>
                <span>
                  {departmentById.get(category.departmentId)?.name || category.departmentId}
                </span>
                <span>{category.description || '-'}</span>
                <span>
                  {statusLabel(category.status)} · 排序 {category.sortOrder}
                </span>
                {canWrite ? (
                  <div className="button-row">
                    <button
                      className="secondary-button"
                      onClick={() => openEditCategory(category)}
                      type="button"
                    >
                      编辑
                    </button>
                    <button
                      className="danger-button"
                      onClick={() => void handleDeleteCategory(category)}
                      type="button"
                    >
                      删除
                    </button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      </section>

      {showSpaceModal ? (
        <KnowledgeSpaceModal
          onClose={() => setShowSpaceModal(false)}
          onSubmit={handleSubmitSpace}
          space={editingSpace}
        />
      ) : null}
      {showCategoryModal ? (
        <KnowledgeCategoryModal
          category={editingCategory}
          defaultDepartmentId={selectedDepartmentId}
          defaultSpaceId={selectedSpaceId}
          departments={departments}
          onClose={() => setShowCategoryModal(false)}
          onSubmit={handleSubmitCategory}
          spaces={spaces}
        />
      ) : null}
    </div>
  );
}

function formatClassificationStats(stats?: KnowledgeClassificationStats | null) {
  const value = stats ?? {
    totalCount: 0,
    processingCount: 0,
    readyCount: 0,
    failedCount: 0,
    unclassifiedCount: 0,
  };
  return `总数 ${value.totalCount} · 解析中 ${value.processingCount} · 成功 ${value.readyCount} · 失败 ${value.failedCount} · 未分类 ${value.unclassifiedCount}`;
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    ACTIVE: '启用',
    INACTIVE: '停用',
    DISABLED: '停用',
  };
  return map[status] || status;
}

function categoryTypeLabel(type: string) {
  const map: Record<string, string> = {
    PROJECT: '项目',
    TOPIC: '专题',
  };
  return map[type] || type;
}
