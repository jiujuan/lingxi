import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { errorMessage } from '../../../api/client';
import { queryKeys } from '../../../api/queryClient';
import { hasPermission } from '../../../auth/authStore';
import { formatDateTime } from '../../../shared/format';
import { EditIcon, TrashIcon } from '../../../shared/ManagementListIcons';
import {
  createUser,
  deleteUser,
  disableUser,
  enableUser,
  listDepartments,
  listRoleOptions,
  listUsers,
  resetUserPassword,
  updateUser,
} from '../api/orgApi';
import { ResetPasswordModal } from '../components/ResetPasswordModal';
import { UserFormModal } from '../components/UserFormModal';
import type {
  AdminUser,
  Pagination,
  UserCreatePayload,
  UserListFilters,
  UserPayload,
} from '../types';

const INITIAL_FILTERS: UserListFilters = {
  keyword: '',
  departmentId: '',
  status: '',
  page: 1,
  pageSize: 20,
};

export function UserPage() {
  const queryClient = useQueryClient();
  const canWrite = hasPermission('USER_WRITE');
  const canReadRoles = hasPermission('ROLE_READ');

  const [filters, setFilters] = useState<UserListFilters>(INITIAL_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState<UserListFilters>(INITIAL_FILTERS);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [resetting, setResetting] = useState<AdminUser | null>(null);

  const usersQuery = useQuery({
    queryKey: queryKeys.users(appliedFilters),
    queryFn: () => listUsers(appliedFilters),
  });
  const departmentsQuery = useQuery({
    queryKey: queryKeys.departments(),
    queryFn: listDepartments,
  });
  const rolesQuery = useQuery({
    queryKey: queryKeys.roleOptions(),
    queryFn: listRoleOptions,
    enabled: canReadRoles,
  });

  const users = usersQuery.data?.data ?? [];
  const pagination = usersQuery.data?.pagination;
  const departments = departmentsQuery.data?.data ?? [];
  const roles = rolesQuery.data?.data ?? [];

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ['users'] });
    void queryClient.invalidateQueries({ queryKey: queryKeys.departments() });
  }

  const createMutation = useMutation({ mutationFn: createUser, onSuccess: invalidate });
  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UserPayload }) =>
      updateUser(id, payload),
    onSuccess: invalidate,
  });
  const resetMutation = useMutation({
    mutationFn: ({ id, password }: { id: string; password: string }) =>
      resetUserPassword(id, password),
  });
  const disableMutation = useMutation({ mutationFn: disableUser, onSuccess: invalidate });
  const enableMutation = useMutation({ mutationFn: enableUser, onSuccess: invalidate });
  const deleteMutation = useMutation({ mutationFn: deleteUser, onSuccess: invalidate });

  function applyFilters() {
    setAppliedFilters({ ...filters, page: 1 });
    setFilters((current) => ({ ...current, page: 1 }));
  }

  function clearFilters() {
    setFilters(INITIAL_FILTERS);
    setAppliedFilters(INITIAL_FILTERS);
  }

  function changePage(page: number) {
    setAppliedFilters((current) => ({ ...current, page }));
    setFilters((current) => ({ ...current, page }));
  }

  function toggleStatus(user: AdminUser) {
    if (user.status === 'ACTIVE') {
      if (window.confirm(`确认禁用 ${user.name}？其登录会话会立即失效。`)) {
        disableMutation.mutate(user.id);
      }
    } else {
      enableMutation.mutate(user.id);
    }
  }

  function remove(user: AdminUser) {
    if (window.confirm(`确认删除用户 ${user.name}（${user.email}）？该操作不可恢复。`)) {
      deleteMutation.mutate(user.id);
    }
  }

  const actionError =
    disableMutation.error ?? enableMutation.error ?? deleteMutation.error;

  return (
    <div className="page-stack">
      <section className="toolbar-row">
        <div>
          <p className="eyebrow">组织架构</p>
          <h2>用户管理</h2>
        </div>
        {canWrite ? (
          <button
            onClick={() => {
              setEditing(null);
              setShowForm(true);
            }}
            type="button"
          >
            新建用户
          </button>
        ) : null}
      </section>
      {usersQuery.isError ? (
        <div className="error-box">{errorMessage(usersQuery.error, '用户数据加载失败')}</div>
      ) : null}
      {actionError ? (
        <div className="error-box">{errorMessage(actionError, '操作失败')}</div>
      ) : null}
      <section className="panel">
        <div className="filter-grid">
          <label>
            关键字
            <input
              onChange={(event) =>
                setFilters((current) => ({ ...current, keyword: event.target.value }))
              }
              placeholder="姓名或邮箱"
              value={filters.keyword}
            />
          </label>
          <label>
            部门
            <select
              onChange={(event) =>
                setFilters((current) => ({ ...current, departmentId: event.target.value }))
              }
              value={filters.departmentId}
            >
              <option value="">全部部门</option>
              {departments.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}（{item.code}）
                </option>
              ))}
            </select>
          </label>
          <label>
            状态
            <select
              onChange={(event) =>
                setFilters((current) => ({ ...current, status: event.target.value }))
              }
              value={filters.status}
            >
              <option value="">全部状态</option>
              <option value="ACTIVE">启用</option>
              <option value="DISABLED">禁用</option>
            </select>
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
          <h3>用户列表</h3>
        </div>
        <div aria-label="用户列表" className="management-list user-management-list" role="table">
          <div className="management-list-head" role="row">
            <span role="columnheader">用户</span>
            <span role="columnheader">部门</span>
            <span role="columnheader">角色</span>
            <span role="columnheader">状态</span>
            <span role="columnheader">创建时间</span>
            <span role="columnheader">操作</span>
          </div>
          {users.length === 0 && !usersQuery.isLoading ? (
            <p className="management-list-empty">没有匹配的用户</p>
          ) : null}
          {users.map((user) => (
            <div className="management-list-row" key={user.id} role="row">
              <div className="management-list-primary" role="cell">
                <strong>{user.name}</strong>
                <span>{user.email}</span>
              </div>
              <span className="management-list-cell" role="cell">
                {user.departmentName ?? '未分配部门'}
              </span>
              <span className="management-list-cell" role="cell">
                {user.roles.map((role) => role.name).join('、') || '无角色'}
              </span>
              <span className={`status-tag status-${user.status.toLowerCase()}`} role="cell">
                {user.status === 'ACTIVE' ? '启用' : '禁用'}
              </span>
              <span className="management-list-cell" role="cell">
                {formatDateTime(user.createdAt)}
              </span>
              {canWrite ? (
                <div className="management-list-actions" role="cell">
                  <button
                    className="management-list-action"
                    onClick={() => {
                      setEditing(user);
                      setShowForm(true);
                    }}
                    type="button"
                  >
                    <EditIcon />
                    编辑
                  </button>
                  <button
                    className="management-list-action"
                    onClick={() => setResetting(user)}
                    type="button"
                  >
                    重置密码
                  </button>
                  <button
                    className="management-list-action"
                    onClick={() => toggleStatus(user)}
                    type="button"
                  >
                    {user.status === 'ACTIVE' ? '禁用' : '启用'}
                  </button>
                  <button
                    className="management-list-action danger"
                    onClick={() => remove(user)}
                    type="button"
                  >
                    <TrashIcon />
                    删除
                  </button>
                </div>
              ) : null}
            </div>
          ))}
        </div>
        {pagination ? (
          <UserPagination onChange={changePage} pagination={pagination} />
        ) : null}
      </section>
      {showForm ? (
        <UserFormModal
          departments={departments}
          onClose={() => setShowForm(false)}
          onCreate={(payload: UserCreatePayload) => createMutation.mutateAsync(payload).then(() => undefined)}
          onUpdate={(id: string, payload: UserPayload) =>
            updateMutation.mutateAsync({ id, payload }).then(() => undefined)
          }
          roles={roles}
          user={editing}
        />
      ) : null}
      {resetting ? (
        <ResetPasswordModal
          onClose={() => setResetting(null)}
          onSubmit={(id: string, password: string) =>
            resetMutation.mutateAsync({ id, password }).then(() => undefined)
          }
          user={resetting}
        />
      ) : null}
    </div>
  );
}

function UserPagination({
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
        共 {pagination.totalItems} 人 · 每页 {pagination.pageSize} 条
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
