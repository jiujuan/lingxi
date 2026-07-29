import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { errorMessage } from '../../../api/client';
import { queryKeys } from '../../../api/queryClient';
import { hasPermission } from '../../../auth/authStore';
import { formatDateTime } from '../../../shared/format';
import { EditIcon, TrashIcon } from '../../../shared/ManagementListIcons';
import {
  createDepartment,
  deleteDepartment,
  listDepartments,
  updateDepartment,
} from '../api/orgApi';
import { DepartmentFormModal } from '../components/DepartmentFormModal';
import type { Department, DepartmentPayload } from '../types';

type TreeRow = { department: Department; depth: number };

/** Flatten the parent/child relation into a depth-annotated display order. */
function buildTreeRows(departments: Department[]): TreeRow[] {
  const ids = new Set(departments.map((item) => item.id));
  const byParent = new Map<string, Department[]>();
  const roots: Department[] = [];
  for (const department of departments) {
    // Treat departments whose parent is missing from the list as roots so
    // nothing silently disappears.
    if (department.parentId && ids.has(department.parentId)) {
      const siblings = byParent.get(department.parentId) ?? [];
      siblings.push(department);
      byParent.set(department.parentId, siblings);
    } else {
      roots.push(department);
    }
  }
  const rows: TreeRow[] = [];
  function visit(department: Department, depth: number) {
    rows.push({ department, depth });
    for (const child of byParent.get(department.id) ?? []) {
      visit(child, depth + 1);
    }
  }
  roots.forEach((root) => visit(root, 0));
  return rows;
}

export function DepartmentPage() {
  const queryClient = useQueryClient();
  const canWrite = hasPermission('USER_WRITE');
  const departmentsQuery = useQuery({
    queryKey: queryKeys.departments(),
    queryFn: listDepartments,
  });
  const [editing, setEditing] = useState<Department | null>(null);
  const [showForm, setShowForm] = useState(false);

  const departments = departmentsQuery.data?.data ?? [];
  const rows = buildTreeRows(departments);

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.departments() });
    void queryClient.invalidateQueries({ queryKey: ['users'] });
  }

  const createMutation = useMutation({ mutationFn: createDepartment, onSuccess: invalidate });
  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: DepartmentPayload }) =>
      updateDepartment(id, payload),
    onSuccess: invalidate,
  });
  const deleteMutation = useMutation({ mutationFn: deleteDepartment, onSuccess: invalidate });

  function openCreate() {
    setEditing(null);
    setShowForm(true);
  }

  function openEdit(department: Department) {
    setEditing(department);
    setShowForm(true);
  }

  function remove(department: Department) {
    if (window.confirm(`确认删除部门「${department.name}」？`)) {
      deleteMutation.mutate(department.id);
    }
  }

  async function submitForm(payload: DepartmentPayload) {
    if (editing) {
      await updateMutation.mutateAsync({ id: editing.id, payload });
    } else {
      await createMutation.mutateAsync(payload);
    }
  }

  return (
    <div className="page-stack">
      <section className="toolbar-row">
        <div>
          <p className="eyebrow">组织架构</p>
          <h2>部门管理</h2>
        </div>
        {canWrite ? (
          <button onClick={openCreate} type="button">
            新建部门
          </button>
        ) : null}
      </section>
      {departmentsQuery.isError ? (
        <div className="error-box">
          {errorMessage(departmentsQuery.error, '部门数据加载失败')}
        </div>
      ) : null}
      {deleteMutation.isError ? (
        <div className="error-box">{errorMessage(deleteMutation.error, '删除失败')}</div>
      ) : null}
      <section className="panel management-list-panel">
        <div className="management-list-heading">
          <h3>部门列表</h3>
        </div>
        <div aria-label="部门列表" className="management-list department-list" role="table">
          <div className="management-list-head" role="row">
            <span role="columnheader">部门名称</span>
            <span role="columnheader">编码</span>
            <span role="columnheader">成员数</span>
            <span role="columnheader">创建时间</span>
            <span role="columnheader">操作</span>
          </div>
          {rows.length === 0 && !departmentsQuery.isLoading ? (
            <p className="management-list-empty">暂无部门，点击右上角「新建部门」创建。</p>
          ) : null}
          {rows.map(({ department, depth }) => (
            <div className="management-list-row" key={department.id} role="row">
              <div className="management-list-primary" role="cell">
                <strong style={{ paddingLeft: `${depth * 1.5}rem` }}>
                  {depth > 0 ? '└ ' : ''}
                  {department.name}
                </strong>
              </div>
              <span className="management-list-cell" role="cell">
                {department.code}
              </span>
              <span className="management-list-cell" role="cell">
                {department.userCount} 人
              </span>
              <span className="management-list-cell" role="cell">
                {formatDateTime(department.createdAt)}
              </span>
              {canWrite ? (
                <div className="management-list-actions" role="cell">
                  <button
                    className="management-list-action"
                    onClick={() => openEdit(department)}
                    type="button"
                  >
                    <EditIcon />
                    编辑
                  </button>
                  <button
                    className="management-list-action danger"
                    onClick={() => remove(department)}
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
      </section>
      {showForm ? (
        <DepartmentFormModal
          department={editing}
          departments={departments}
          onClose={() => setShowForm(false)}
          onSubmit={submitForm}
        />
      ) : null}
    </div>
  );
}
