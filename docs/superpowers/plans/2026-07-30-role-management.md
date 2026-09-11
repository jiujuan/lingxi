# 角色管理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每个租户提供独立的角色管理页面与后端 CRUD/权限分配 API，同时保护内置角色并阻止删除仍被用户使用的角色。

**Architecture:** 将角色管理从 `UserAdminService`/`user_repo.py` 中拆出，新增 `RoleRepository`、`RoleService`、角色 schema 和 `/api/v1/roles` 路由；继续复用 `Role`、`RolePermission`、`UserRole` 和 `Permission` 表。前端新增 `features/role`，通过 `#roles` 路由和现有管理列表视觉系统展示数据，表单按权限模块分组。

**Tech Stack:** Python 3.13、FastAPI、SQLAlchemy、Alembic、Pydantic、pytest、React 19、TypeScript、TanStack Query、Vite、Playwright（Python）。

---

## 文件结构

| 路径 | 责任 |
|---|---|
| `server/app/models/role.py` | 为 `Role` 增加内置角色持久化字段。 |
| `server/app/db/migrations/versions/0005_role_management.py` | 幂等地添加/删除 `roles.is_builtin`，并回填初始化角色。 |
| `server/app/repositories/role_repo.py` | 角色、权限、关联计数和关联表的持久化查询。 |
| `server/app/services/role_service.py` | 当前租户边界、业务规则、审计和事务。 |
| `server/app/schemas/role.py` | 角色 API 输入输出模型。 |
| `server/app/api/v1/roles.py` | 受 `ROLE_READ`/`ROLE_WRITE` 保护的 REST API。 |
| `server/app/api/v1/__init__.py` | 注册角色路由。 |
| `server/app/api/v1/users.py` | 移除旧的重复 `GET /roles` 路由。 |
| `server/app/schemas/user.py` | 移除仅供旧角色列表 API 使用的 schema。 |
| `server/app/services/seed_service.py` | 初始化角色标记为内置。 |
| `server/tests/test_role_admin.py` | 角色领域和 HTTP API 回归覆盖。 |
| `web/admin/src/features/role/types.ts` | 前端角色、权限、筛选和载荷类型。 |
| `web/admin/src/features/role/api/roleApi.ts` | 角色 API 客户端。 |
| `web/admin/src/features/role/components/RoleFormModal.tsx` | 新建、编辑和只读查看角色的权限表单。 |
| `web/admin/src/features/role/pages/RolePage.tsx` | 角色列表、搜索、分页和操作状态。 |
| `web/admin/src/routes/index.tsx` | `#roles` 路由、菜单条目和侧边栏图标。 |
| `web/admin/src/styles.css` | 角色列表的桌面列宽与移动端无溢出布局。 |
| `web/admin/tests/t18_admin_list_playwright.py` | 角色菜单和桌面/移动列表视觉验收。 |

### Task 1: 添加后端角色 API 的失败验收测试

**Files:**
- Create: `server/tests/test_role_admin.py`
- Reference: `server/tests/test_org_admin.py`, `server/tests/test_auth_rbac.py`, `server/tests/test_model_config.py`

- [ ] **Step 1: 写角色列表与详情 API 的失败测试。**

```python
from server.tests.test_auth_rbac import build_test_client
from server.tests.test_model_config import login_admin


def test_role_list_detail_and_permission_catalog():
    client, _ = build_test_client()
    headers = login_admin(client)

    listed = client.get('/api/v1/roles', headers=headers)
    assert listed.status_code == 200
    admin = next(item for item in listed.json()['data'] if item['code'] == 'SYSTEM_ADMIN')
    assert admin['isBuiltin'] is True
    assert admin['scope'] == 'TENANT'
    assert admin['userCount'] >= 1
    assert admin['permissionCount'] > 0

    detail = client.get(f"/api/v1/roles/{admin['id']}", headers=headers)
    assert detail.status_code == 200
    assert {permission['code'] for permission in detail.json()['permissions']} >= {'ROLE_READ', 'ROLE_WRITE'}

    catalog = client.get('/api/v1/roles/available-permissions', headers=headers)
    assert catalog.status_code == 200
    assert any(item['code'] == 'ROLE_READ' for item in catalog.json()['data'])
```

- [ ] **Step 2: 运行测试确认在实现前失败。**

Run: `python -m pytest server/tests/test_role_admin.py::test_role_list_detail_and_permission_catalog -v`

Expected: FAIL，因为当前 `/api/v1/roles` 仅返回 `id/code/name`，且不存在详情和权限目录接口。

- [ ] **Step 3: 写创建、更新、内置角色保护和删除保护的失败测试。**

```python
def test_custom_role_crud_and_delete_guards():
    client, _ = build_test_client()
    headers = login_admin(client)
    permissions = client.get('/api/v1/roles/available-permissions', headers=headers).json()['data']
    role_read_id = next(item['id'] for item in permissions if item['code'] == 'ROLE_READ')

    created = client.post('/api/v1/roles', headers=headers, json={
        'name': '审计查看者', 'code': 'AUDIT_VIEWER', 'permissionIds': [role_read_id],
    })
    assert created.status_code == 200
    role = created.json()
    assert role['isBuiltin'] is False
    assert role['permissions'][0]['id'] == role_read_id

    duplicate = client.post('/api/v1/roles', headers=headers, json={
        'name': '重复角色', 'code': 'audit_viewer', 'permissionIds': [],
    })
    assert duplicate.status_code == 409
    assert duplicate.json()['error']['code'] == 'ROLE_CODE_EXISTS'

    updated = client.put(f"/api/v1/roles/{role['id']}", headers=headers, json={
        'name': '审计只读', 'code': 'AUDIT_VIEWER', 'permissionIds': [],
    })
    assert updated.status_code == 200
    assert updated.json()['name'] == '审计只读'

    builtin = next(item for item in client.get('/api/v1/roles', headers=headers).json()['data'] if item['isBuiltin'])
    protected = client.put(f"/api/v1/roles/{builtin['id']}", headers=headers, json={
        'name': builtin['name'], 'code': builtin['code'], 'permissionIds': [],
    })
    assert protected.status_code == 400
    assert protected.json()['error']['code'] == 'BUILTIN_ROLE_PROTECTED'

    assigned_user = client.post('/api/v1/users', headers=headers, json={
        'email': 'audit.user@example.com', 'name': 'Audit User', 'password': 'AuditUser123!', 'roleIds': [role['id']],
    })
    assert assigned_user.status_code == 200
    blocked = client.delete(f"/api/v1/roles/{role['id']}", headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()['error']['code'] == 'ROLE_HAS_USERS'
    assert blocked.json()['error']['message'] == '请先解除关联用户后再删除'
```

- [ ] **Step 4: 运行创建/保护测试确认失败。**

Run: `python -m pytest server/tests/test_role_admin.py::test_custom_role_crud_and_delete_guards -v`

Expected: FAIL，因为 POST、PUT、DELETE 路由和业务规则尚不存在。

- [ ] **Step 5: 写读写权限边界的失败测试。**

```python
def test_role_endpoints_require_role_permissions():
    client, _ = build_test_client()
    employee_headers = {
        'Authorization': f"Bearer {client.post('/api/v1/auth/login', json={'email': 'employee@example.com', 'password': 'Employee123!'}).json()['accessToken']}"
    }

    assert client.get('/api/v1/roles', headers=employee_headers).status_code == 403
    assert client.post('/api/v1/roles', headers=employee_headers, json={
        'name': '无权创建', 'code': 'DENIED', 'permissionIds': [],
    }).status_code == 403
```

- [ ] **Step 6: 运行权限测试确认失败。**

Run: `python -m pytest server/tests/test_role_admin.py::test_role_endpoints_require_role_permissions -v`

Expected: FAIL，因为新 API 路由尚未注册。

### Task 2: 实现角色模型、迁移和种子数据

**Files:**
- Modify: `server/app/models/role.py`
- Create: `server/app/db/migrations/versions/0005_role_management.py`
- Modify: `server/app/services/seed_service.py`
- Test: `server/tests/test_role_admin.py`

- [ ] **Step 1: 为模型加内置角色字段。**

```python
from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint

class Role(IdMixin, TimestampMixin, Base):
    # existing columns...
    is_builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default='0'
    )
```

- [ ] **Step 2: 新建幂等 Alembic 迁移并回填内置角色。**

```python
revision = '0005_role_management'
down_revision = '0004_knowledge_classification'


def upgrade() -> None:
    bind = op.get_bind()
    role_columns = {column['name'] for column in sa.inspect(bind).get_columns('roles')}
    if 'is_builtin' not in role_columns:
        op.add_column('roles', sa.Column('is_builtin', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(sa.text("UPDATE roles SET is_builtin = 1 WHERE code IN ('SYSTEM_ADMIN', 'KNOWLEDGE_ADMIN', 'EMPLOYEE')"))
```

`downgrade()` 对存在的 `is_builtin` 使用 `batch_alter_table('roles')` 删除该列，保持 SQLite 兼容。

- [ ] **Step 3: 令全新种子数据也标记内置角色。**

```python
role = Role(
    tenant_id=tenant.id,
    code=role_code,
    name=role_name,
    scope='TENANT',
    is_builtin=role_code in ROLE_PERMISSION_MAP,
)
```

同时在已有租户的 `seed_identity_data()` 路径中，将初始化角色更新为 `is_builtin=True`，避免只依赖迁移。

- [ ] **Step 4: 运行 Task 1 的列表测试，确认模型/种子层已使结构性断言前进，但 API 仍失败。**

Run: `python -m pytest server/tests/test_role_admin.py::test_role_list_detail_and_permission_catalog -v`

Expected: 仍为 FAIL，失败原因应集中在角色 API 响应字段、详情或权限目录路由，不应出现数据库列缺失。

- [ ] **Step 5: 提交模型和迁移。**

```bash
git add server/app/models/role.py server/app/db/migrations/versions/0005_role_management.py server/app/services/seed_service.py
git commit -m "feat(rbac): mark built-in roles"
```

### Task 3: 实现角色仓储、schema、服务和 API

**Files:**
- Create: `server/app/repositories/role_repo.py`
- Create: `server/app/schemas/role.py`
- Create: `server/app/services/role_service.py`
- Create: `server/app/api/v1/roles.py`
- Modify: `server/app/api/v1/__init__.py`
- Modify: `server/app/api/v1/users.py`
- Modify: `server/app/schemas/user.py`
- Modify: `server/app/services/user_admin_service.py`
- Test: `server/tests/test_role_admin.py`

- [ ] **Step 1: 实现 `RoleRepository` 的租户限定查询和关联操作。**

```python
class RoleRepository:
    def search(self, tenant_id: str, *, keyword: str | None, page: int, page_size: int) -> tuple[list[tuple[Role, int, int]], int]: ...
    def get_for_tenant(self, tenant_id: str, role_id: str) -> Role | None: ...
    def get_by_code(self, tenant_id: str, code: str) -> Role | None: ...
    def list_permissions(self) -> list[Permission]: ...
    def list_permissions_by_ids(self, permission_ids: list[str]) -> list[Permission]: ...
    def permissions_for_role(self, role_id: str) -> list[Permission]: ...
    def user_count(self, role_id: str) -> int: ...
    def replace_permissions(self, role_id: str, permission_ids: list[str]) -> None: ...
    def delete(self, role: Role) -> None: ...
```

`search()` 使用外连接到 `UserRole` 和 `RolePermission` 的两个计数子查询，防止多对多连接相乘导致用户数/权限数被放大；所有角色筛选都带 `Role.tenant_id == tenant_id`。

- [ ] **Step 2: 定义角色 schema 和别名。**

```python
class RoleUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=80)
    permission_ids: list[str] = Field(default_factory=list, alias='permissionIds')

    @field_validator('code')
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()

class RoleResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    name: str
    code: str
    scope: str
    is_builtin: bool = Field(alias='isBuiltin')
    user_count: int = Field(alias='userCount')
    permission_count: int = Field(alias='permissionCount')
    created_at: str = Field(alias='createdAt')
```

另外定义 `PermissionResponse`、`RoleDetailResponse`（含 `permissions`）、`RoleListResponse`（含现有 `PaginationResponse`）和 `PermissionListResponse`。

- [ ] **Step 3: 实现 `RoleService` 的全部业务规则。**

```python
class RoleService:
    def list_roles(self, context: AccessContext, *, keyword: str | None, page: int, page_size: int) -> dict: ...
    def get_role(self, context: AccessContext, role_id: str) -> dict: ...
    def list_available_permissions(self, context: AccessContext) -> dict: ...
    def create_role(self, context: AccessContext, *, name: str, code: str, permission_ids: list[str]) -> dict: ...
    def update_role(self, context: AccessContext, role_id: str, *, name: str, code: str, permission_ids: list[str]) -> dict: ...
    def delete_role(self, context: AccessContext, role_id: str) -> None: ...
```

规则：重复编码抛出 `conflict('ROLE_CODE_EXISTS', '角色编码已存在')`；不属于当前租户的角色抛出 `not_found('角色不存在')`；无效权限抛出 `bad_request('PERMISSION_NOT_FOUND', '包含不存在的权限')`；内置角色写操作抛出 `bad_request('BUILTIN_ROLE_PROTECTED', '内置角色不允许修改或删除')`；关联用户数大于零时抛出 `conflict('ROLE_HAS_USERS', '请先解除关联用户后再删除')`。写操作写入 `AuditLog`，`resource_type='ROLE'`，动作为 `ROLE_CREATED`、`ROLE_UPDATED`、`ROLE_DELETED`，然后提交事务。

- [ ] **Step 4: 实现独立 `roles.py` 路由并确保静态路径先注册。**

```python
router = APIRouter(tags=['roles'])

@router.get('/roles/available-permissions', response_model=PermissionListResponse)
def list_available_permissions(
    context: AccessContext = Depends(require_permission('ROLE_READ')),
    db: Session = Depends(get_db),
) -> dict:
    return RoleService(db).list_available_permissions(context)

@router.get('/roles/{role_id}', response_model=RoleDetailResponse)
def get_role(...): ...
```

实现后依序定义 `GET /roles`、`POST /roles`、`PUT /roles/{role_id}`、`DELETE /roles/{role_id}`。从 `server/app/api/v1/__init__.py` 导入 `roles` 并调用 `api_router.include_router(roles.router)`。由于旧的同路径 `GET /roles` 已删除，角色列表只有一个权威路由。

- [ ] **Step 5: 让用户管理的角色选择读取独立仓储。**

将 `UserAdminService` 对 `RoleRepository` 的 import 改为 `from server.app.repositories.role_repo import RoleRepository`；从 `users.py` 删除现有 `GET /roles` 函数及 `RoleListResponse` import，并从 `schemas/user.py` 删除 `RoleListResponse`。角色列表唯一由独立 `roles.py` 提供；它额外返回的字段不会影响用户表单读取 `id/code/name`。

- [ ] **Step 6: 运行所有角色后端测试并修正到通过。**

Run: `python -m pytest server/tests/test_role_admin.py -v`

Expected: PASS，三个测试均通过。

- [ ] **Step 7: 运行现有组织管理回归测试。**

Run: `python -m pytest server/tests/test_org_admin.py -v`

Expected: PASS，用户管理仍可列出、分配并读取角色。

- [ ] **Step 8: 提交角色后端领域模块。**

```bash
git add server/app/repositories/role_repo.py server/app/schemas/role.py server/app/services/role_service.py server/app/api/v1/roles.py server/app/api/v1/__init__.py server/app/services/user_admin_service.py server/tests/test_role_admin.py
git commit -m "feat(rbac): add role management API"
```

### Task 4: 添加角色页的失败浏览器验收

**Files:**
- Modify: `web/admin/tests/t18_admin_list_playwright.py`
- Reference: `web/admin/src/features/org/pages/UserPage.tsx`

- [ ] **Step 1: 为 Playwright mock 增加角色管理 API 契约。**

在 `mock_api()` 中增加：

```python
if method == 'GET' and path == '/api/v1/roles':
    fulfill_json(route, {
        'data': [{
            'id': 'role-system-admin', 'name': '系统管理员', 'code': 'SYSTEM_ADMIN',
            'scope': 'TENANT', 'isBuiltin': True, 'userCount': 1,
            'permissionCount': 24, 'createdAt': '2026-07-29T09:00:00+08:00',
        }, {
            'id': 'role-audit-viewer', 'name': '审计查看者', 'code': 'AUDIT_VIEWER',
            'scope': 'TENANT', 'isBuiltin': False, 'userCount': 0,
            'permissionCount': 1, 'createdAt': '2026-07-29T09:00:00+08:00',
        }],
        'pagination': {'page': 1, 'pageSize': 20, 'totalItems': 2, 'totalPages': 1},
    })
    return
```

同时为 `GET /api/v1/roles/available-permissions` 和 `GET /api/v1/roles/{id}` 返回匹配的权限目录/详情数据。

- [ ] **Step 2: 写角色页面的失败断言。**

在 `verify_admin_lists()` 用户页断言后加入：

```python
page.goto(f'{APP_URL}/#roles', wait_until='networkidle')
expect(page.get_by_role('heading', name='角色列表')).to_be_visible()
expect(page.get_by_text('系统管理员', exact=True)).to_be_visible()
expect(page.get_by_text('内置', exact=True)).to_be_visible()
expect(page.get_by_role('button', name='查看').first).to_be_visible()
expect(page.get_by_role('button', name='编辑').first).to_be_visible()
if suffix == 'desktop':
    expect(page.get_by_role('columnheader', name='角色')).to_be_visible()
assert_no_overflow(page, '角色管理')
```

- [ ] **Step 3: 运行 Playwright 验收确认失败。**

Run: `python web/admin/tests/t18_admin_list_playwright.py`

Expected: FAIL，因为 `#roles` 路由、菜单和角色页均不存在。

### Task 5: 实现前端角色类型、API 客户端和页面

**Files:**
- Create: `web/admin/src/features/role/types.ts`
- Create: `web/admin/src/features/role/api/roleApi.ts`
- Create: `web/admin/src/features/role/pages/RolePage.tsx`
- Modify: `web/admin/src/routes/index.tsx`
- Modify: `web/admin/src/styles.css`
- Test: `web/admin/tests/t18_admin_list_playwright.py`

- [ ] **Step 1: 声明前端角色 API 类型。**

```ts
export type RolePermission = { id: string; code: string; module: string; action: string; description: string | null };
export type ManagedRole = {
  id: string; name: string; code: string; scope: string; isBuiltin: boolean;
  userCount: number; permissionCount: number; createdAt: string;
};
export type RoleDetail = ManagedRole & { permissions: RolePermission[] };
export type RolePayload = { name: string; code: string; permissionIds: string[] };
export type RoleListResult = { data: ManagedRole[]; pagination: Pagination };
```

- [ ] **Step 2: 实现 API 客户端。**

```ts
export function listRoles(filters: RoleListFilters) {
  const params = new URLSearchParams({ page: String(filters.page), pageSize: String(filters.pageSize) });
  if (filters.keyword) params.set('keyword', filters.keyword);
  return apiRequest<RoleListResult>(`/api/v1/roles?${params}`);
}
export const getRole = (id: string) => apiRequest<RoleDetail>(`/api/v1/roles/${id}`);
export const listAvailablePermissions = () => apiRequest<{ data: RolePermission[] }>('/api/v1/roles/available-permissions');
export const createRole = (payload: RolePayload) => apiRequest<RoleDetail>('/api/v1/roles', { method: 'POST', body: JSON.stringify(payload) });
export const updateRole = (id: string, payload: RolePayload) => apiRequest<RoleDetail>(`/api/v1/roles/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
export const deleteRole = (id: string) => apiRequest<{ ok: boolean }>(`/api/v1/roles/${id}`, { method: 'DELETE' });
```

- [ ] **Step 3: 实现列表页面。**

`RolePage` 使用 `useQuery` 请求 `listRoles()`，用 `useMutation` 执行创建、更新和删除，并在成功后 `invalidateQueries({ queryKey: ['roles'] })`。页面使用已有 `page-header`、`filter-bar`、`management-list-panel`、`management-list`、`management-list-row`、`management-list-action`、`status-tag` 和 `logs-pagination` 样式，列标题严格为“角色”“编码”“作用范围”“关联用户”“权限数”“创建时间”“操作”。在 `styles.css` 增加 `.role-management-list` 的桌面 7 列 grid 和 `max-width: 680px` 下隐藏表头/重排数据行规则，确保移动端无水平溢出。

每个角色行：

```tsx
<span className={role.isBuiltin ? 'status-tag status-active' : 'status-tag'} role="cell">
  {role.isBuiltin ? '内置' : '自定义'}
</span>
{role.isBuiltin ? (
  <button className="management-list-action" onClick={() => openDetail(role)} type="button">查看</button>
) : (
  <>
    <button className="management-list-action" onClick={() => openEdit(role)} type="button">编辑</button>
    <button className="management-list-action danger" onClick={() => void remove(role)} type="button">删除</button>
  </>
)}
```

`remove()` 先调用 `window.confirm('确定删除该自定义角色吗？')`，再执行 mutation；错误用 `errorMessage(error, '删除角色失败')` 呈现在现有 `error-box`。仅当 `hasPermission('ROLE_WRITE')` 时显示“新增角色”和自定义角色写操作。

- [ ] **Step 4: 将独立页面挂入路由和菜单。**

在 `routes/index.tsx`：导入 `RolePage`；向 `SidebarIconName` 增加 `'role'`，用盾牌 SVG 绘制；紧随 `#users` 路由后插入：

```tsx
{
  hash: '#roles',
  icon: 'role',
  label: '角色管理',
  permission: 'ROLE_READ',
  render: () => <RolePage />,
},
```

- [ ] **Step 5: 运行 TypeScript 检查确认基础页面能编译。**

Run: `npm run typecheck`

Working directory: `web/admin`

Expected: PASS。

### Task 6: 实现角色权限表单和浏览器验收

**Files:**
- Create: `web/admin/src/features/role/components/RoleFormModal.tsx`
- Modify: `web/admin/src/features/role/pages/RolePage.tsx`
- Modify: `web/admin/tests/t18_admin_list_playwright.py`
- Test: `web/admin/tests/t18_admin_list_playwright.py`

- [ ] **Step 1: 实现 `RoleFormModal` 的新增、编辑和只读模式。**

```ts
type Props = {
  mode: 'create' | 'edit' | 'view';
  role: RoleDetail | null;
  permissions: RolePermission[];
  onClose: () => void;
  onCreate: (payload: RolePayload) => Promise<void>;
  onUpdate: (roleId: string, payload: RolePayload) => Promise<void>;
};
```

按 `permission.module` 对权限分组：

```ts
const permissionGroups = Object.entries(
  permissions.reduce<Record<string, RolePermission[]>>((groups, permission) => {
    (groups[permission.module] ??= []).push(permission);
    return groups;
  }, {}),
).sort(([left], [right]) => left.localeCompare(right));
```

表单使用 `name`、`code`、只读 `TENANT` 和每个权限的 checkbox。`mode === 'view'` 时所有输入禁用、隐藏保存按钮、标题为“查看角色”；`mode !== 'view'` 时保存失败以 `error-box` 呈现且按钮显示“保存中…”。

- [ ] **Step 2: 从页面加载权限目录和详情。**

在 `RolePage` 对话框打开时，用 `getRole(role.id)` 取得编辑/查看完整权限，首次打开新建表单时确保 `listAvailablePermissions()` 已加载。对详情和权限目录分别显示加载与错误状态；编辑/查看在详情尚未加载时不渲染空表单。

- [ ] **Step 3: 扩展 Playwright 验收，覆盖内置角色只读和自定义角色操作。**

```python
builtin_row = page.get_by_role('row').filter(has_text='系统管理员')
expect(builtin_row.get_by_role('button', name='查看')).to_be_visible()
expect(builtin_row.get_by_role('button', name='编辑')).to_have_count(0)

custom_row = page.get_by_role('row').filter(has_text='审计查看者')
expect(custom_row.get_by_role('button', name='编辑')).to_be_visible()
expect(custom_row.get_by_role('button', name='删除')).to_be_visible()
```

- [ ] **Step 4: 运行角色 Playwright 验收并修正到通过。**

Run: `python web/admin/tests/t18_admin_list_playwright.py`

Expected: PASS，输出 `T18 admin list visual acceptance passed`。

- [ ] **Step 5: 运行前端生产构建。**

Run: `npm run build`

Working directory: `web/admin`

Expected: PASS，`tsc --noEmit && vite build` 均为零错误。

- [ ] **Step 6: 提交角色前端。**

```bash
git add web/admin/src/features/role web/admin/src/routes/index.tsx web/admin/src/styles.css web/admin/tests/t18_admin_list_playwright.py
git commit -m "feat(admin): add role management page"
```

### Task 7: 集成回归与完成核验

**Files:**
- Modify if required by failures: only files listed in Tasks 2–6

- [ ] **Step 1: 运行完整后端测试套件。**

Run: `python -m pytest server/tests -q`

Expected: PASS，零失败。

- [ ] **Step 2: 执行数据库迁移验证。**

Run: `alembic upgrade head`

Expected: PASS，`0005_role_management` 被应用，`roles.is_builtin` 存在且初始化角色被回填。

- [ ] **Step 3: 运行前端静态和浏览器验收。**

Run:

```bash
npm run lint
npm run typecheck
npm run build
python tests/t18_admin_list_playwright.py
```

Working directory: `web/admin`

Expected: 四个命令均以 exit code 0 完成。

- [ ] **Step 4: 检查最终差异与工作区边界。**

Run:

```bash
git diff --check
git status --short
git log --oneline -3
```

Expected: 不出现空白错误；仅报告本任务改动以及开始前已存在的未提交文件；日志包含本计划各提交。

- [ ] **Step 5: 如回归修复产生新改动，单独提交。**

```bash
git add <only-the-verified-role-management-files>
git commit -m "fix(rbac): complete role management integration"
```

不要暂存或提交任务开始前已经存在的 `.gitignore`、验收截图、`docs/design/v1.1/analysis/retrieval-pipeline-analysis.md`、`docs/development/knowledge-category/` 或现有 `docs/superpowers/plans/` 改动。
