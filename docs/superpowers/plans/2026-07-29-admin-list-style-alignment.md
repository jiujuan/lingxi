# 后台管理列表样式统一 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 API 调用日志、模型配置、部门管理和用户管理列表采用日志排障页面相同的紧凑表格视觉与文字操作样式，同时保持现有数据和行为不变。

**Architecture:** 各页面继续拥有自己的查询、权限和 mutation 逻辑，只将列表 JSX 改为共享的 `management-list` 展示约定。`styles.css` 提供基础表格、操作按钮、移动端重排和用户分页样式；各列表使用修饰类声明自己的列宽。编辑和删除图标放入一个小型共享图标模块，避免手写 SVG 在三个页面中重复。

**Tech Stack:** React 19、TypeScript、TanStack Query、Vite、Playwright、全局 CSS。

---

### Task 1: 添加列表视觉回归测试

**Files:**
- Create: `web/admin/tests/t18_admin_list_playwright.py`

- [ ] **Step 1: 写出失败的验收测试**

创建对 `/api/v1/api-call-logs`、`/api/v1/model-providers`、`/api/v1/model-configs`、`/api/v1/departments`、`/api/v1/users` 的 mock，并以含 `API_KEY_READ`、`MODEL_CONFIG_READ`、`USER_READ`、`USER_WRITE` 权限的管理员身份访问页面。断言桌面端的表头与操作按钮：

```python
page.goto(f"{APP_URL}/#api-keys", wait_until="networkidle")
expect(page.get_by_role("heading", name="调用日志")).to_be_visible()
expect(page.get_by_role("columnheader", name="请求路径")).to_be_visible()
expect(page.get_by_text("POST /v1/chat/completions")).to_be_visible()

page.goto(f"{APP_URL}/#models", wait_until="networkidle")
expect(page.get_by_role("columnheader", name="供应商名称")).to_be_visible()
expect(page.get_by_role("button", name="编辑").first).to_be_visible()
expect(page.get_by_role("button", name="删除").first).to_be_visible()
```

- [ ] **Step 2: 运行测试，确认当前页面不满足新断言**

Run:

```powershell
python tests\t18_admin_list_playwright.py
```

Expected: FAIL，因为当前 API 调用日志、供应商、模型实例和部门列表没有对应的表头。

- [ ] **Step 3: 补充用户列表与窄屏断言**

在同一测试中断言用户列表的分页文字与页码按钮，并在 `390x844` 视口确认表头隐藏、操作可见且页面没有横向溢出：

```python
expect(page.get_by_text("共 2 人 · 每页 20 条")).to_be_visible()
expect(page.get_by_role("button", name="1")).to_be_visible()
assert_no_overflow(page, "用户管理")
```

- [ ] **Step 4: 暂不提交**

测试与实现将在同一个功能提交中提交，避免形成只包含失败测试的 `main` 提交。

### Task 2: 建立共享的管理列表图标与基础样式

**Files:**
- Create: `web/admin/src/shared/ManagementListIcons.tsx`
- Modify: `web/admin/src/styles.css:1614-1970`

- [ ] **Step 1: 新增编辑和删除图标模块**

创建两个无障碍隐藏的 SVG 图标，供文字操作按钮使用：

```tsx
type IconProps = { className?: string };

export function EditIcon({ className }: IconProps) {
  return (
    <svg aria-hidden="true" className={className} fill="none" viewBox="0 0 24 24">
      <path d="M4 16.75V20h3.25L18.4 8.85l-3.25-3.25L4 16.75Z" stroke="currentColor" strokeWidth="1.8" />
      <path d="m13.9 6.85 3.25 3.25" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}
```

`TrashIcon` 采用相同的 `IconProps` 和 `currentColor`，包含垃圾桶轮廓路径。

- [ ] **Step 2: 添加管理列表基础 CSS**

新增 `.management-list-panel`、`.management-list-heading`、`.management-list`、`.management-list-head`、`.management-list-row`、`.management-list-primary`、`.management-list-cell`、`.management-list-actions`、`.management-list-action` 和 `.management-list-action.danger`。关键尺寸如下：

```css
.management-list-head { min-height: 44px; }
.management-list-row { min-height: 62px; }
.management-list-action {
  background: transparent;
  border: 0;
  border-radius: 5px;
  color: #3475e6;
  font-size: 14px;
  padding: 5px 8px;
}
.management-list-action:hover:not(:disabled) {
  background: #eaf2ff;
  color: #2563eb;
}
.management-list-action.danger { color: #e45560; }
.management-list-action.danger:hover:not(:disabled) {
  background: #fff0f1;
  color: #d63c4a;
}
```

- [ ] **Step 3: 添加桌面列定义和移动端规则**

为 `.api-call-log-list`、`.model-provider-list`、`.model-config-list`、`.department-list`、`.user-management-list` 设置各自的 `grid-template-columns`。在 `@media (max-width: 860px)` 中隐藏 `.management-list-head`，让行采用 `minmax(0, 1fr) auto` 两列，把普通数据单元放到整行，并让操作处于第一行右侧。

- [ ] **Step 4: 运行类型检查**

Run:

```powershell
npm run typecheck
```

Expected: PASS。

### Task 3: 重构 API 调用日志与模型配置列表展示

**Files:**
- Modify: `web/admin/src/features/api-keys/components/ApiCallLogTable.tsx`
- Modify: `web/admin/src/features/model-config/pages/ModelConfigPage.tsx`

- [ ] **Step 1: 将 API 调用日志转换为带表头的管理列表**

保留 `logs: ApiCallLog[]` 输入，改用如下的表格语义结构：

```tsx
<section className="panel management-list-panel">
  <div className="management-list-heading"><h3>调用日志</h3></div>
  <div aria-label="调用日志" className="management-list api-call-log-list" role="table">
    <div className="management-list-head" role="row">
      <span role="columnheader">请求路径</span>
      <span role="columnheader">Key 前缀</span>
      <span role="columnheader">HTTP 状态</span>
      <span role="columnheader">耗时</span>
      <span role="columnheader">请求 ID</span>
    </div>
  </div>
</section>
```

每条数据使用主列 `METHOD path` 和创建时间副文本，保留 Key 前缀、HTTP 状态、耗时和请求 ID。接口没有分页元数据，不添加分页控件。

- [ ] **Step 2: 将供应商列表改成管理列表**

在 `ModelConfigPage.tsx` 中把供应商映射改为 `role="table"`，表头依次为“供应商名称”“类型”“Secret 配置”“状态”“操作”。名称和 `baseUrl` 放入主列，保留测试连接、编辑、删除 handlers；编辑按钮带 `EditIcon`，删除按钮带 `TrashIcon` 和 `danger` 类。

- [ ] **Step 3: 将模型实例列表改成管理列表**

表头依次为“模型名称”“能力”“默认标识”“状态”“操作”。主列副文本显示原 `providerId`，保留设为默认、编辑和删除 handlers，以及 `isDefault` 的 disabled 状态。

- [ ] **Step 4: 运行新验收测试**

Run:

```powershell
python tests\t18_admin_list_playwright.py
```

Expected: API Key 与模型配置的桌面表头、操作按钮断言通过。

### Task 4: 重构部门与用户管理列表展示

**Files:**
- Modify: `web/admin/src/features/org/pages/DepartmentPage.tsx`
- Modify: `web/admin/src/features/org/pages/UserPage.tsx`

- [ ] **Step 1: 将部门树行转换为管理列表**

表头为“部门名称”“编码”“成员数”“创建时间”“操作”。保留 `buildTreeRows` 顺序、层级缩进以及 `USER_WRITE` 权限判断；编辑、删除按钮仅在可写时渲染，并使用共享图标及文字操作样式。

- [ ] **Step 2: 将用户列表转换为管理列表**

表头为“用户”“部门”“角色”“状态”“创建时间”“操作”。姓名/邮箱保留主/副文本结构，角色、状态和创建时间的值不变，所有原有操作 handlers 保留。

- [ ] **Step 3: 用日志页同款分页替换用户分页外观**

在 `UserPage.tsx` 本地添加与日志页一致的页码计算函数，使用 `logs-pagination`、`logs-pagination-actions`、`logs-page-button` 和 `logs-page-ellipsis` 结构渲染页码：

```tsx
<div className="logs-pagination">
  <span>共 {pagination.totalItems} 人 · 每页 {pagination.pageSize} 条</span>
  <div className="logs-pagination-actions">
    <button className="logs-page-button logs-page-label" onClick={() => changePage(pagination.page - 1)}>
      ‹ 上一页
    </button>
  </div>
</div>
```

上一页/下一页的 disabled 条件与现有实现一致；页码按钮调用既有 `changePage`。

- [ ] **Step 4: 运行新验收测试**

Run:

```powershell
python tests\t18_admin_list_playwright.py
```

Expected: 部门、用户表头、用户分页、桌面和移动端无溢出断言通过。

### Task 5: 全量验证与提交

**Files:**
- Modify: `web/admin/tests/t18_admin_list_playwright.py`
- Modify: `web/admin/src/shared/ManagementListIcons.tsx`
- Modify: `web/admin/src/features/api-keys/components/ApiCallLogTable.tsx`
- Modify: `web/admin/src/features/model-config/pages/ModelConfigPage.tsx`
- Modify: `web/admin/src/features/org/pages/DepartmentPage.tsx`
- Modify: `web/admin/src/features/org/pages/UserPage.tsx`
- Modify: `web/admin/src/styles.css`

- [ ] **Step 1: 执行静态与构建检查**

Run:

```powershell
npm run typecheck
npm run build
```

Expected: 两个命令均以退出码 0 结束。

- [ ] **Step 2: 执行既有与新增浏览器验收**

Run:

```powershell
python tests\t17_release_playwright.py
python tests\t18_admin_list_playwright.py
```

Expected: 两个脚本均输出通过信息。

- [ ] **Step 3: 执行视觉验收**

在 1440px 和 390px 视口检查 API Key、模型配置、部门管理、用户管理：

```python
assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
```

检查操作按钮默认透明、悬停显示浅蓝背景，删除悬停显示浅红背景；确认没有黑色外框。

- [ ] **Step 4: 提交功能改动**

Run:

```powershell
git add -- web/admin/src/shared/ManagementListIcons.tsx web/admin/src/features/api-keys/components/ApiCallLogTable.tsx web/admin/src/features/model-config/pages/ModelConfigPage.tsx web/admin/src/features/org/pages/DepartmentPage.tsx web/admin/src/features/org/pages/UserPage.tsx web/admin/src/styles.css web/admin/tests/t18_admin_list_playwright.py
git commit -m "feat: align admin management list styles"
```

Expected: 一个只包含后台列表视觉统一及其回归测试的提交。
