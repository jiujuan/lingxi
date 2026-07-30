import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { errorMessage } from '../../../api/client';
import { queryKeys } from '../../../api/queryClient';
import { hasPermission } from '../../../auth/authStore';
import { formatDateTime } from '../../../shared/format';
import { EditIcon, TrashIcon } from '../../../shared/ManagementListIcons';
import { deleteRole, listRoles } from '../api/roleApi';
import type { Pagination, Role, RoleListFilters } from '../types';

const INITIAL_FILTERS: RoleListFilters = {
  keyword: '',
  page: 1,
  pageSize: 20,
};

type PendingForm = {
  mode: 'create' | 'edit' | 'view';
  role: Role | null;
};

export function RolePage() {
  const queryClient = useQueryClient();
  const canWrite = hasPermission('ROLE_WRITE');
  const [filters, setFilters] = useState<RoleListFilters>(INITIAL_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState<RoleListFilters>(INITIAL_FILTERS);
  const [pendingForm, setPendingForm] = useState<PendingForm | null>(null);

  const rolesQuery = useQuery({
    queryKey: ['roles', appliedFilters],
    queryFn: () => listRoles(appliedFilters),
  });
  const deleteMutation = useMutation({
    mutationFn: deleteRole,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['roles'] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.roleOptions() });
    },
  });

  const roles = rolesQuery.data?.data ?? [];
  const pagination = rolesQuery.data?.pagination;

  function applyFilters() {
    const nextFilters = { ...filters, page: 1 };
    setFilters(nextFilters);
    setAppliedFilters(nextFilters);
  }

  function clearFilters() {
    setFilters(INITIAL_FILTERS);
    setAppliedFilters(INITIAL_FILTERS);
  }

  function changePage(page: number) {
    setFilters((current) => ({ ...current, page }));
    setAppliedFilters((current) => ({ ...current, page }));
  }

  function requestForm(mode: PendingForm['mode'], role: Role | null) {
    // TODO(Task 6): Replace this explicit placeholder with RoleFormModal.
    setPendingForm({ mode, role });
  }

  function remove(role: Role) {
    if (window.confirm('确定删除该自定义角色吗？')) {
      deleteMutation.mutate(role.id);
    }
  }

  return (
    <div className="page-stack role-management-page">
      <section className="toolbar-row page-header">
        <div>
          <p className="eyebrow">组织架构</p>
          <h2>角色管理</h2>
        </div>
        {canWrite ? (
          <button onClick={() => requestForm('create', null)} type="button">
            新建角色
          </button>
        ) : null}
      </section>
      {rolesQuery.isError ? (
        <div className="error-box">{errorMessage(rolesQuery.error, '角色数据加载失败')}</div>
      ) : null}
      {deleteMutation.error ? (
        <div className="error-box">{errorMessage(deleteMutation.error, '删除角色失败')}</div>
      ) : null}
      {pendingForm ? (
        <div aria-live="polite" className="role-form-todo">
          {pendingForm.mode === 'create'
            ? '角色新建表单将在后续任务中实现。'
            : `${pendingForm.role?.name ?? '该角色'}的${
                pendingForm.mode === 'view' ? '查看' : '编辑'
              }表单将在后续任务中实现。`}
        </div>
      ) : null}
      <section className="panel filter-bar">
        <div className="filter-grid">
          <label>
            关键字
            <input
              onChange={(event) =>
                setFilters((current) => ({ ...current, keyword: event.target.value }))
              }
              placeholder="角色名称或编码"
              value={filters.keyword}
            />
          </label>
          <div className="button-row user-filter-actions">
            <button onClick={applyFilters} type="button">
              查询
            </button>
            <button className="secondary-button" onClick={clearFilters} type="button">
              重置
            </button>
          </div>
        </div>
      </section>
      <section className="panel management-list-panel">
        <div className="management-list-heading">
          <h3>角色列表</h3>
        </div>
        <div aria-label="角色列表" className="management-list role-management-list" role="table">
          <div className="management-list-head" role="row">
            <span role="columnheader">角色</span>
            <span role="columnheader">编码</span>
            <span role="columnheader">作用范围</span>
            <span role="columnheader">关联用户</span>
            <span role="columnheader">权限数</span>
            <span role="columnheader">创建时间</span>
            <span role="columnheader">操作</span>
          </div>
          {roles.length === 0 && !rolesQuery.isLoading ? (
            <p className="management-list-empty">没有匹配的角色</p>
          ) : null}
          {roles.map((role) => (
            <div className="management-list-row" key={role.id} role="row">
              <div className="management-list-primary" role="cell">
                <strong>{role.name}</strong>
                <span className="status-tag">{role.isBuiltin ? '内置' : '自定义'}</span>
              </div>
              <span className="management-list-cell" role="cell">
                {role.code}
              </span>
              <span className="management-list-cell" role="cell">
                {scopeLabel(role.scope)}
              </span>
              <span className="management-list-cell" role="cell">
                {role.userCount}
              </span>
              <span className="management-list-cell" role="cell">
                {role.permissionCount}
              </span>
              <span className="management-list-cell" role="cell">
                {formatDateTime(role.createdAt)}
              </span>
              <div className="management-list-actions" role="cell">
                <button
                  className="management-list-action"
                  onClick={() => requestForm('view', role)}
                  type="button"
                >
                  查看
                </button>
                {canWrite && !role.isBuiltin ? (
                  <>
                    <button
                      className="management-list-action"
                      onClick={() => requestForm('edit', role)}
                      type="button"
                    >
                      <EditIcon />
                      编辑
                    </button>
                    <button
                      className="management-list-action danger"
                      onClick={() => remove(role)}
                      type="button"
                    >
                      <TrashIcon />
                      删除
                    </button>
                  </>
                ) : null}
              </div>
            </div>
          ))}
        </div>
        {pagination ? <RolePagination onChange={changePage} pagination={pagination} /> : null}
      </section>
    </div>
  );
}

function scopeLabel(scope: string) {
  return scope === 'TENANT' ? '租户' : scope;
}

function RolePagination({
  onChange,
  pagination,
}: {
  onChange: (page: number) => void;
  pagination: Pagination;
}) {
  const totalPages = Math.max(pagination.totalPages, 1);
  const pages = pageNumbers(pagination.page, totalPages);

  return (
    <div className="logs-pagination">
      <span>
        共 {pagination.totalItems} 条，第 {pagination.page}/{totalPages} 页
      </span>
      <div className="logs-pagination-actions">
        <button
          className="logs-page-button logs-page-label"
          disabled={pagination.page <= 1}
          onClick={() => onChange(pagination.page - 1)}
          type="button"
        >
          ‹ 上一页
        </button>
        {pages.map((page, index) =>
          page === 'ellipsis' ? (
            <span className="logs-page-ellipsis" key={`ellipsis-${index}`}>
              …
            </span>
          ) : (
            <button
              aria-current={page === pagination.page ? 'page' : undefined}
              className={page === pagination.page ? 'logs-page-button active' : 'logs-page-button'}
              key={page}
              onClick={() => onChange(page)}
              type="button"
            >
              {page}
            </button>
          ),
        )}
        <button
          className="logs-page-button logs-page-label"
          disabled={pagination.page >= totalPages}
          onClick={() => onChange(pagination.page + 1)}
          type="button"
        >
          下一页 ›
        </button>
      </div>
    </div>
  );
}

function pageNumbers(currentPage: number, totalPages: number): Array<number | 'ellipsis'> {
  if (totalPages <= 5) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }
  if (currentPage <= 3) {
    return [1, 2, 3, 'ellipsis', totalPages];
  }
  if (currentPage >= totalPages - 2) {
    return [1, 'ellipsis', totalPages - 2, totalPages - 1, totalPages];
  }
  return [1, 'ellipsis', currentPage, 'ellipsis', totalPages];
}
