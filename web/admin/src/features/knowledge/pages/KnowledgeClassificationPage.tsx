import { useCallback, useEffect, useMemo, useState } from 'react';

import { ApiError, errorMessage } from '../../../api/client';
import { hasPermission } from '../../../auth/authStore';
import { formatDateTime } from '../../../shared/format';
import {
  createDepartment,
  deleteDepartment,
  listDepartments,
  updateDepartment,
} from '../../org/api/orgApi';
import type { Department, DepartmentPayload } from '../../org/types';
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
import { ClassificationDeleteConfirmModal } from '../components/ClassificationDeleteConfirmModal';
import { ClassificationDepartmentModal } from '../components/ClassificationDepartmentModal';
import {
  ClassificationMigrationModal,
  type ClassificationMigrationSource,
} from '../components/ClassificationMigrationModal';
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

type ClassificationTab = 'SPACE' | 'DEPARTMENT' | 'CATEGORY';

type DeleteTarget =
  | { type: 'SPACE'; item: KnowledgeSpace }
  | { type: 'DEPARTMENT'; item: Department }
  | { type: 'CATEGORY'; item: KnowledgeCategory };

export function KnowledgeClassificationPage() {
  const canManageClassification = hasPermission('DOCUMENT_WRITE');
  const canManageDepartments = hasPermission('USER_WRITE');
  const [activeTab, setActiveTab] = useState<ClassificationTab>('SPACE');
  const [keyword, setKeyword] = useState('');
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
  const [editingDepartment, setEditingDepartment] = useState<Department | null>(null);
  const [showDepartmentModal, setShowDepartmentModal] = useState(false);
  const [editingCategory, setEditingCategory] = useState<KnowledgeCategory | null>(null);
  const [showCategoryModal, setShowCategoryModal] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [deletePending, setDeletePending] = useState(false);
  const [migrationSource, setMigrationSource] = useState<ClassificationMigrationSource | null>(
    null,
  );

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
  const normalizedKeyword = keyword.trim().toLocaleLowerCase();
  const visibleSpaces = useMemo(
    () => spaces.filter((space) => matchesKeyword(normalizedKeyword, space.name, space.code, space.description)),
    [normalizedKeyword, spaces],
  );
  const visibleDepartments = useMemo(
    () =>
      departments.filter((department) =>
        matchesKeyword(
          normalizedKeyword,
          department.name,
          department.code,
          departmentById.get(department.parentId ?? '')?.name,
        ),
      ),
    [departmentById, departments, normalizedKeyword],
  );
  const visibleCategories = useMemo(
    () =>
      categories.filter((category) =>
        matchesKeyword(
          normalizedKeyword,
          category.name,
          category.code,
          category.description,
          categoryTypeLabel(category.categoryType),
        ),
      ),
    [categories, normalizedKeyword],
  );

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

  function openCreateDepartment() {
    setEditingDepartment(null);
    setShowDepartmentModal(true);
  }

  function openEditDepartment(department: Department) {
    setEditingDepartment(department);
    setShowDepartmentModal(true);
  }

  function openCreateCategory() {
    setEditingCategory(null);
    setShowCategoryModal(true);
  }

  function openEditCategory(category: KnowledgeCategory) {
    setEditingCategory(category);
    setShowCategoryModal(true);
  }

  function openActiveCreate() {
    if (activeTab === 'SPACE') {
      openCreateSpace();
      return;
    }
    if (activeTab === 'DEPARTMENT') {
      openCreateDepartment();
      return;
    }
    openCreateCategory();
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

  async function handleSubmitSpace(
    payload: CreateKnowledgeSpacePayload | UpdateKnowledgeSpacePayload,
  ) {
    if (editingSpace) {
      await handleUpdateSpace(editingSpace.id, payload as UpdateKnowledgeSpacePayload);
      return;
    }
    await handleCreateSpace(payload as CreateKnowledgeSpacePayload);
  }

  async function handleSubmitDepartment(payload: DepartmentPayload) {
    if (editingDepartment) {
      await updateDepartment(editingDepartment.id, payload);
      setNotice('部门已更新。');
    } else {
      await createDepartment(payload);
      setNotice('部门已创建。');
    }
    await Promise.all([loadDepartments(), loadCategories(), loadCategoryStats()]);
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

  async function handleSubmitCategory(
    payload: CreateKnowledgeCategoryPayload | UpdateKnowledgeCategoryPayload,
  ) {
    if (editingCategory) {
      await handleUpdateCategory(editingCategory.id, payload as UpdateKnowledgeCategoryPayload);
      return;
    }
    await handleCreateCategory(payload as CreateKnowledgeCategoryPayload);
  }

  function requestDelete(target: DeleteTarget) {
    setNotice(null);
    setDeleteTarget(target);
  }

  async function confirmDelete() {
    if (!deleteTarget) {
      return;
    }
    setDeletePending(true);
    try {
      if (deleteTarget.type === 'DEPARTMENT') {
        await deleteDepartment(deleteTarget.item.id);
        setNotice('部门已删除。');
        await Promise.all([loadDepartments(), loadCategories(), loadCategoryStats()]);
        setDeleteTarget(null);
        return;
      }

      if (deleteTarget.type === 'SPACE') {
        await deleteKnowledgeSpace(deleteTarget.item.id);
        setNotice('知识库空间已删除。');
        await Promise.all([loadSpaces(), loadSpaceStats(), loadCategoryStats()]);
        if (deleteTarget.item.id === selectedSpaceId) {
          setCategories([]);
          setCategoryStats([]);
          setCategoryUnclassifiedStats(null);
        }
        setDeleteTarget(null);
        return;
      }

      await deleteKnowledgeCategory(deleteTarget.item.id);
      setNotice('项目 / 专题已删除。');
      await Promise.all([loadCategories(), loadCategoryStats(), loadSpaceStats()]);
      setDeleteTarget(null);
    } catch (caught) {
      if (deleteTarget.type === 'SPACE') {
        const documentCount = deleteDocumentConflictCount(caught, 'KNOWLEDGE_SPACE_HAS_DOCUMENTS');
        if (documentCount !== null) {
          setMigrationSource({
            type: 'SPACE',
            id: deleteTarget.item.id,
            name: deleteTarget.item.name,
            documentCount,
          });
          setSpacesError(
            `知识库空间「${deleteTarget.item.name}」下仍有 ${documentCount} 篇文档，请先迁移。`,
          );
          setDeleteTarget(null);
          return;
        }
        setSpacesError(errorMessage(caught, '知识库空间删除失败。'));
      } else if (deleteTarget.type === 'CATEGORY') {
        const documentCount = deleteDocumentConflictCount(caught, 'KNOWLEDGE_CATEGORY_HAS_DOCUMENTS');
        if (documentCount !== null) {
          setMigrationSource({
            type: 'CATEGORY',
            id: deleteTarget.item.id,
            name: deleteTarget.item.name,
            documentCount,
          });
          setCategoriesError(
            `项目 / 专题「${deleteTarget.item.name}」下仍有 ${documentCount} 篇文档，请先迁移。`,
          );
          setDeleteTarget(null);
          return;
        }
        setCategoriesError(errorMessage(caught, '项目 / 专题删除失败。'));
      } else {
        setDepartmentsError(errorMessage(caught, '部门删除失败。'));
      }
    } finally {
      setDeletePending(false);
    }
  }

  async function handleMigrationSuccess() {
    setMigrationSource(null);
    setNotice('文档迁移成功，请重新执行删除。');
    await Promise.all([loadSpaces(), loadCategories(), loadSpaceStats(), loadCategoryStats()]);
  }

  const activeCanWrite =
    activeTab === 'DEPARTMENT' ? canManageDepartments : canManageClassification;
  const activeCreateLabel =
    activeTab === 'SPACE'
      ? '增加知识库空间'
      : activeTab === 'DEPARTMENT'
        ? '增加部门'
        : '增加专题 / 项目';
  const activeDescription =
    activeTab === 'SPACE'
      ? '管理知识库的业务空间与基础信息。'
      : activeTab === 'DEPARTMENT'
        ? '维护分类维度使用的部门组织。'
        : '按知识库空间和部门维护专题 / 项目。';
  const emptyMessage =
    activeTab === 'SPACE'
      ? '暂无知识库空间'
      : activeTab === 'DEPARTMENT'
        ? '暂无部门'
        : '暂无专题 / 项目';
  const deleteDescription =
    deleteTarget?.type === 'SPACE'
      ? '删除后无法恢复。若该空间下有文档，系统会引导你先迁移关联文档。'
      : deleteTarget?.type === 'CATEGORY'
        ? '删除后无法恢复。若该专题 / 项目下有文档，系统会引导你先迁移关联文档。'
        : '删除后无法恢复。请确认该部门不再用于其他管理流程。';

  return (
    <div className="page-stack classification-page">
      <section className="classification-page-header">
        <div>
          <p className="eyebrow">知识库中心</p>
          <h2>知识库分类管理</h2>
          <p className="muted">维护知识库空间、部门与专题 / 项目。</p>
        </div>
        <div className="toolbar-actions">
          <a className="secondary-link" href="#knowledge">
            返回知识库中心
          </a>
          {activeCanWrite ? (
            <button
              disabled={
                activeTab === 'CATEGORY' && (!selectedSpaceId || !selectedDepartmentId)
              }
              onClick={openActiveCreate}
              type="button"
            >
              <PlusIcon />
              {activeCreateLabel}
            </button>
          ) : null}
        </div>
      </section>

      {notice ? <div className="status-pill">{notice}</div> : null}

      <section className="classification-table-panel">
        <div className="classification-tabs-toolbar">
          <div aria-label="分类维度" className="classification-tabs" role="tablist">
            <TabButton
              active={activeTab === 'SPACE'}
              icon={<KnowledgeSpaceIcon />}
              label="知识库空间"
              onClick={() => setActiveTab('SPACE')}
            />
            <TabButton
              active={activeTab === 'DEPARTMENT'}
              icon={<DepartmentIcon />}
              label="部门"
              onClick={() => setActiveTab('DEPARTMENT')}
            />
            <TabButton
              active={activeTab === 'CATEGORY'}
              icon={<CategoryIcon />}
              label="专题 / 项目"
              onClick={() => setActiveTab('CATEGORY')}
            />
          </div>
          <label className="classification-search">
            <SearchIcon />
            <span className="sr-only">搜索当前分类</span>
            <input
              aria-label="搜索当前分类"
              onChange={(event) => setKeyword(event.target.value)}
              placeholder={`搜索${tabLabel(activeTab)}`}
              type="search"
              value={keyword}
            />
          </label>
        </div>

        <div className="classification-list-intro">
          <div>
            <h3>{tabLabel(activeTab)}</h3>
            <p className="muted">{activeDescription}</p>
          </div>
          <button
            aria-label={`刷新${tabLabel(activeTab)}`}
            className="icon-button classification-refresh-button"
            onClick={() => {
              if (activeTab === 'SPACE') {
                void Promise.all([loadSpaces(), loadSpaceStats()]);
              } else if (activeTab === 'DEPARTMENT') {
                void loadDepartments();
              } else {
                void Promise.all([loadCategories(), loadCategoryStats()]);
              }
            }}
            title={`刷新${tabLabel(activeTab)}`}
            type="button"
          >
            <RefreshIcon />
          </button>
        </div>

        {activeTab === 'CATEGORY' ? (
          <div className="classification-scope-filters">
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
            {selectedSpaceId && selectedDepartmentId ? (
              <p className="classification-stats-summary">
                当前范围未分类：{formatClassificationStats(categoryUnclassifiedStats)}
              </p>
            ) : null}
          </div>
        ) : null}

        {activeTab === 'SPACE' && spacesError ? <div className="error-box">{spacesError}</div> : null}
        {activeTab === 'DEPARTMENT' && departmentsError ? (
          <div className="error-box">{departmentsError}</div>
        ) : null}
        {activeTab === 'CATEGORY' && categoriesError ? (
          <div className="error-box">{categoriesError}</div>
        ) : null}
        {activeTab !== 'DEPARTMENT' && statsError ? <div className="error-box">{statsError}</div> : null}

        {activeTab === 'SPACE' ? (
          <>
            {spaceStatsLoading ? <p className="muted">正在加载空间统计...</p> : null}
            <p className="classification-stats-summary">
              全局未分类：{formatClassificationStats(spaceStatsSummary)}
            </p>
            <div className="classification-list" role="list">
              <div aria-hidden="true" className="classification-list-head classification-space-head">
                <span>空间名称</span>
                <span>编码</span>
                <span>描述</span>
                <span>文档统计</span>
                <span>状态</span>
                <span>更新时间</span>
                <span>操作</span>
              </div>
              {spacesLoading ? <p className="muted classification-loading">正在加载知识库空间...</p> : null}
              {!spacesLoading && !visibleSpaces.length ? (
                <EmptyState message={normalizedKeyword ? '未找到匹配的知识库空间' : emptyMessage} />
              ) : null}
              {visibleSpaces.map((space) => (
                <div className="classification-list-row classification-space-row" key={space.id} role="listitem">
                  <button
                    className="classification-entity link-button"
                    onClick={() => {
                      setSelectedSpaceId(space.id);
                      setActiveTab('CATEGORY');
                    }}
                    type="button"
                  >
                    <span className="classification-entity-icon">
                      <KnowledgeSpaceIcon />
                    </span>
                    <span>
                      <strong>{space.name}</strong>
                      <small>{space.id === selectedSpaceId ? '当前筛选空间' : '查看关联专题 / 项目'}</small>
                    </span>
                  </button>
                  <code>{space.code}</code>
                  <span className="classification-cell-muted">{space.description || '-'}</span>
                  <span className="classification-stats">
                    {formatClassificationStats(spaceStatsById.get(space.id))}
                  </span>
                  <span>
                    <StatusTag status={space.status} />
                    <small>排序 {space.sortOrder}</small>
                  </span>
                  <span className="classification-cell-muted">
                    {formatDateTime(space.updatedAt || space.createdAt)}
                  </span>
                  {canManageClassification ? (
                    <ActionButtons
                      onDelete={() => requestDelete({ type: 'SPACE', item: space })}
                      onEdit={() => openEditSpace(space)}
                    />
                  ) : (
                    <span />
                  )}
                </div>
              ))}
            </div>
          </>
        ) : null}

        {activeTab === 'DEPARTMENT' ? (
          <div className="classification-list" role="list">
            <div aria-hidden="true" className="classification-list-head classification-department-head">
              <span>部门名称</span>
              <span>部门编码</span>
              <span>上级部门</span>
              <span>用户数</span>
              <span>创建时间</span>
              <span>操作</span>
            </div>
            {departmentsLoading ? <p className="muted classification-loading">正在加载部门...</p> : null}
            {!departmentsLoading && !visibleDepartments.length ? (
              <EmptyState message={normalizedKeyword ? '未找到匹配的部门' : emptyMessage} />
            ) : null}
            {visibleDepartments.map((department) => (
              <div
                className="classification-list-row classification-department-row"
                key={department.id}
                role="listitem"
              >
                <div className="classification-entity">
                  <span className="classification-entity-icon department-icon">
                    <DepartmentIcon />
                  </span>
                  <span>
                    <strong>{department.name}</strong>
                    <small>{department.parentId ? '下级部门' : '顶级部门'}</small>
                  </span>
                </div>
                <code>{department.code}</code>
                <span className="classification-cell-muted">
                  {departmentById.get(department.parentId ?? '')?.name || '-'}
                </span>
                <span>{department.userCount} 位用户</span>
                <span className="classification-cell-muted">{formatDateTime(department.createdAt)}</span>
                {canManageDepartments ? (
                  <ActionButtons
                    onDelete={() => requestDelete({ type: 'DEPARTMENT', item: department })}
                    onEdit={() => openEditDepartment(department)}
                  />
                ) : (
                  <span />
                )}
              </div>
            ))}
          </div>
        ) : null}

        {activeTab === 'CATEGORY' ? (
          <>
            {categoryStatsLoading ? <p className="muted">正在加载专题 / 项目统计...</p> : null}
            {!selectedSpaceId || !selectedDepartmentId ? (
              <EmptyState message="请选择空间和分类部门" />
            ) : (
              <div className="classification-list" role="list">
                <div aria-hidden="true" className="classification-list-head classification-category-head">
                  <span>专题 / 项目</span>
                  <span>编码</span>
                  <span>类型</span>
                  <span>文档统计</span>
                  <span>描述</span>
                  <span>状态</span>
                  <span>操作</span>
                </div>
                {categoriesLoading ? <p className="muted classification-loading">正在加载专题 / 项目...</p> : null}
                {!categoriesLoading && !visibleCategories.length ? (
                  <EmptyState
                    message={
                      normalizedKeyword
                        ? '未找到匹配的专题 / 项目'
                        : `${emptyMessage}：${selectedSpace?.name || selectedSpaceId} / ${selectedDepartment?.name || selectedDepartmentId}`
                    }
                  />
                ) : null}
                {visibleCategories.map((category) => (
                  <div
                    className="classification-list-row classification-category-row"
                    key={category.id}
                    role="listitem"
                  >
                    <div className="classification-entity">
                      <span className="classification-entity-icon category-icon">
                        <CategoryIcon />
                      </span>
                      <span>
                        <strong>{category.name}</strong>
                        <small>{departmentById.get(category.departmentId)?.name || category.departmentId}</small>
                      </span>
                    </div>
                    <code>{category.code}</code>
                    <span>{categoryTypeLabel(category.categoryType)}</span>
                    <span className="classification-stats">
                      {formatClassificationStats(categoryStatsById.get(category.id))}
                    </span>
                    <span className="classification-cell-muted">{category.description || '-'}</span>
                    <span>
                      <StatusTag status={category.status} />
                      <small>排序 {category.sortOrder}</small>
                    </span>
                    {canManageClassification ? (
                      <ActionButtons
                        onDelete={() => requestDelete({ type: 'CATEGORY', item: category })}
                        onEdit={() => openEditCategory(category)}
                      />
                    ) : (
                      <span />
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        ) : null}
      </section>

      {showSpaceModal ? (
        <KnowledgeSpaceModal
          onClose={() => setShowSpaceModal(false)}
          onSubmit={handleSubmitSpace}
          space={editingSpace}
        />
      ) : null}
      {showDepartmentModal ? (
        <ClassificationDepartmentModal
          department={editingDepartment}
          departments={departments}
          onClose={() => setShowDepartmentModal(false)}
          onSubmit={handleSubmitDepartment}
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
      {deleteTarget ? (
        <ClassificationDeleteConfirmModal
          description={deleteDescription}
          itemName={deleteTarget.item.name}
          onClose={() => setDeleteTarget(null)}
          onConfirm={() => void confirmDelete()}
          pending={deletePending}
        />
      ) : null}
      {migrationSource ? (
        <ClassificationMigrationModal
          onClose={() => setMigrationSource(null)}
          onMigrated={() => void handleMigrationSuccess()}
          source={migrationSource}
        />
      ) : null}
    </div>
  );
}

function TabButton({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      aria-selected={active}
      className="classification-tab"
      onClick={onClick}
      role="tab"
      type="button"
    >
      {icon}
      {label}
    </button>
  );
}

function ActionButtons({ onEdit, onDelete }: { onEdit: () => void; onDelete: () => void }) {
  return (
    <div className="classification-row-actions">
      <button className="classification-action" onClick={onEdit} type="button">
        <EditIcon />
        编辑
      </button>
      <button
        aria-label="删除"
        className="classification-action classification-delete-action"
        onClick={onDelete}
        type="button"
      >
        <TrashIcon />
        删除
      </button>
    </div>
  );
}

function StatusTag({ status }: { status: string }) {
  return <span className={`classification-status is-${status.toLocaleLowerCase()}`}>{statusLabel(status)}</span>;
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="classification-empty-state">
      <CategoryIcon />
      <strong>{message}</strong>
    </div>
  );
}

function deleteDocumentConflictCount(error: unknown, expectedCode: string) {
  if (!(error instanceof ApiError) || error.status !== 409 || error.code !== expectedCode) {
    return null;
  }
  const details = error.details;
  if (!details || typeof details !== 'object') {
    return 0;
  }
  const count = (details as { documentCount?: unknown }).documentCount;
  return typeof count === 'number' && Number.isFinite(count) ? count : 0;
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

function matchesKeyword(keyword: string, ...values: Array<string | null | undefined>) {
  return !keyword || values.some((value) => value?.toLocaleLowerCase().includes(keyword));
}

function tabLabel(tab: ClassificationTab) {
  const labels: Record<ClassificationTab, string> = {
    SPACE: '知识库空间',
    DEPARTMENT: '部门',
    CATEGORY: '专题 / 项目',
  };
  return labels[tab];
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

function PlusIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4 4" />
    </svg>
  );
}

function RefreshIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M20 11a8 8 0 0 0-14.8-4L3 10m1-6v6h6M4 13a8 8 0 0 0 14.8 4L21 14m-1 6v-6h-6" />
    </svg>
  );
}

function KnowledgeSpaceIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M4 5.5 12 3l8 2.5-8 2.5-8-2.5Zm0 5L12 8l8 2.5-8 2.5-8-2.5Zm0 5L12 13l8 2.5-8 2.5-8-2.5Z" />
    </svg>
  );
}

function DepartmentIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M12 4a3 3 0 1 0 0 6 3 3 0 0 0 0-6Zm-6 14a6 6 0 0 1 12 0M5 6.5a2.5 2.5 0 1 0 0 5m14-5a2.5 2.5 0 1 1 0 5m-14 6a4.5 4.5 0 0 1 2-3.75m12 3.75a4.5 4.5 0 0 0-2-3.75" />
    </svg>
  );
}

function CategoryIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H10l2 2h6.5A1.5 1.5 0 0 1 20 7.5v10a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5v-12Z" />
      <path d="M8 12h8M8 15h5" />
    </svg>
  );
}

function EditIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="m4 20 4.2-.9L18 9.3a2.1 2.1 0 0 0-3-3L5.2 16.1 4 20Z" />
      <path d="m13.5 7.8 3 3" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M4 7h16M10 11v5m4-5v5M9 7l1-3h4l1 3m-9 0 1 13h10l1-13" />
    </svg>
  );
}
