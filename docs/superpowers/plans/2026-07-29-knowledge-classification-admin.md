# 知识库分类管理页面改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将知识库分类页面改为三个可 CRUD 的图标化 Tab 列表，并以自定义弹窗完成新增、编辑、删除与已有文档迁移。

**Architecture:** `KnowledgeClassificationPage` 保留空间、部门、专题/项目的数据加载和 mutation 编排，按当前 Tab 渲染相应的列表、搜索结果和操作入口。新增专属的部门表单与删除确认弹窗；空间和专题/项目继续使用已有业务弹窗但改为参考稿的紧凑样式。删除确认完成后，空间和专题/项目仍复用现有迁移冲突处理。

**Tech Stack:** React 19、TypeScript、Vite、既有 REST API、Playwright Python mock 验收。

---

### Task 1: 扩展 T09 分类管理 mock 与验收场景

**Files:**
- Modify: `web/admin/tests/t09_knowledge_playwright.py`

- [ ] **Step 1: 为部门 CRUD 添加 mock 路由与状态更新**

```python
if method == "POST" and path == "/api/v1/departments":
    payload = body or {}
    department = {
        "id": "dept-created",
        "userCount": 0,
        "createdAt": NOW,
        **payload,
    }
    self.departments.append(department)
    fulfill_json(route, department, status=201)
    return

if method == "PUT" and path.startswith("/api/v1/departments/"):
    department_id = path.rsplit("/", 1)[-1]
    department = self._department(department_id)
    department.update(body or {})
    fulfill_json(route, department)
    return

if method == "DELETE" and path.startswith("/api/v1/departments/"):
    department_id = path.rsplit("/", 1)[-1]
    self.departments = [item for item in self.departments if item["id"] != department_id]
    fulfill_json(route, {"ok": True})
    return
```

- [ ] **Step 2: 添加部门 Tab 的失败验收断言**

```python
page.get_by_role("tab", name=re.compile("部门")).click()
page.get_by_role("button", name="增加部门").click()
department_dialog = page.get_by_role("dialog", name="增加部门")
department_dialog.get_by_label("部门名称").fill("运营部")
department_dialog.get_by_label("部门编码").fill("operations")
department_dialog.get_by_role("button", name="保存").click()
expect(page.get_by_text("部门已创建。")).to_be_visible()
assert api.find_request("POST", "/api/v1/departments")["body"] == {
    "name": "运营部",
    "code": "operations",
    "parentId": None,
}
```

- [ ] **Step 3: 添加自定义删除确认弹窗断言**

```python
page.locator(".classification-department-row", has_text="运营部").get_by_role(
    "button", name="删除"
).click()
delete_dialog = page.get_by_role("dialog", name="删除确认")
expect(delete_dialog.get_by_text("确定删除「运营部」吗？")).to_be_visible()
delete_dialog.get_by_role("button", name="确认删除").click()
expect(page.get_by_text("部门已删除。")).to_be_visible()
api.find_request("DELETE", "/api/v1/departments/dept-created")
```

- [ ] **Step 4: 运行测试以确认当前页面无法满足新断言**

Run: `python web\admin\tests\t09_knowledge_playwright.py`  
Expected: FAIL，原因是现有页面没有 `部门` Tab、`增加部门` 按钮与自定义删除确认对话框。

- [ ] **Step 5: 提交测试改动**

```bash
git add web/admin/tests/t09_knowledge_playwright.py
git commit -m "test: cover classification management tabs"
```

### Task 2: 新增分类管理专用弹窗组件

**Files:**
- Create: `web/admin/src/features/knowledge/components/ClassificationDepartmentModal.tsx`
- Create: `web/admin/src/features/knowledge/components/ClassificationDeleteConfirmModal.tsx`
- Modify: `web/admin/src/features/knowledge/components/KnowledgeSpaceModal.tsx`
- Modify: `web/admin/src/features/knowledge/components/KnowledgeCategoryModal.tsx`

- [ ] **Step 1: 创建部门表单弹窗**

```tsx
export function ClassificationDepartmentModal({
  department,
  departments,
  onClose,
  onSubmit,
}: Props) {
  const [name, setName] = useState(department?.name ?? '');
  const [code, setCode] = useState(department?.code ?? '');
  const [parentId, setParentId] = useState(department?.parentId ?? '');

  async function submit(event: FormEvent) {
    event.preventDefault();
    await onSubmit({ name: name.trim(), code: code.trim(), parentId: parentId || null });
    onClose();
  }
}
```

- [ ] **Step 2: 创建自定义删除确认弹窗**

```tsx
export function ClassificationDeleteConfirmModal({
  description,
  itemName,
  onClose,
  onConfirm,
  pending,
}: Props) {
  return (
    <div className="modal-backdrop" role="presentation">
      <section aria-label="删除确认" aria-modal="true" className="modal-panel classification-delete-modal" role="dialog">
        <header className="classification-modal-header">
          <h3>删除确认</h3>
          <button aria-label="关闭" className="icon-button" onClick={onClose} type="button">
            <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m7 7 10 10M17 7 7 17" /></svg>
          </button>
        </header>
        <div aria-hidden="true" className="delete-warning-icon">
          <svg viewBox="0 0 24 24"><path d="M12 8v5m0 3h.01M10.3 3.9 2.5 17.4A2 2 0 0 0 4.2 20h15.6a2 2 0 0 0 1.7-2.6L13.7 3.9a2 2 0 0 0-3.4 0Z" /></svg>
        </div>
        <p className="delete-question">确定删除「{itemName}」吗？</p>
        <p className="muted">{description}</p>
        <footer className="classification-modal-actions">
          <button className="secondary-button" disabled={pending} onClick={onClose} type="button">取消</button>
          <button className="danger-button" disabled={pending} onClick={onConfirm} type="button">
            {pending ? '删除中…' : '确认删除'}
          </button>
        </footer>
      </section>
    </div>
  );
}
```

- [ ] **Step 3: 将空间和专题/项目表单改为紧凑弹窗结构**

```tsx
  <header className="classification-modal-header">
  <h3>{space ? '编辑知识库空间' : '增加知识库空间'}</h3>
  <button aria-label="关闭" className="icon-button" disabled={saving} onClick={onClose} type="button">
    <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m7 7 10 10M17 7 7 17" /></svg>
  </button>
</header>
<form className="classification-form" onSubmit={(event) => void submit(event)}>
  <label>空间名称<input required value={name} onChange={(event) => setName(event.target.value)} /></label>
  <label>空间编码<input required value={code} onChange={(event) => setCode(event.target.value)} /></label>
  <label>描述<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
  <footer className="classification-modal-actions">
    <button className="secondary-button" disabled={saving} onClick={onClose} type="button">取消</button>
    <button disabled={saving} type="submit">{saving ? '保存中…' : '保存'}</button>
  </footer>
</form>
```

- [ ] **Step 4: 运行 TypeScript 检查**

Run: `npm run typecheck` in `web/admin`  
Expected: PASS。

- [ ] **Step 5: 提交弹窗组件改动**

```bash
git add web/admin/src/features/knowledge/components
git commit -m "feat: add classification management modals"
```

### Task 3: 重构分类管理页面为三 Tab 列表

**Files:**
- Modify: `web/admin/src/features/knowledge/pages/KnowledgeClassificationPage.tsx`

- [ ] **Step 1: 添加分类页状态与部门 mutation**

```tsx
type ClassificationTab = 'SPACE' | 'DEPARTMENT' | 'CATEGORY';

const [activeTab, setActiveTab] = useState<ClassificationTab>('SPACE');
const [keyword, setKeyword] = useState('');
const [editingDepartment, setEditingDepartment] = useState<Department | null>(null);
const [showDepartmentModal, setShowDepartmentModal] = useState(false);
const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
```

- [ ] **Step 2: 复用 org API 实现部门新增、编辑、删除并刷新依赖数据**

```tsx
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
```

- [ ] **Step 3: 将删除入口改为先设置确认目标**

```tsx
function requestDelete(target: DeleteTarget) {
  setNotice(null);
  setDeleteTarget(target);
}

async function confirmDelete() {
  if (!deleteTarget) return;
  if (deleteTarget.type === 'DEPARTMENT') {
    await deleteDepartment(deleteTarget.department.id);
    setNotice('部门已删除。');
    await Promise.all([loadDepartments(), loadCategories(), loadCategoryStats()]);
  }
  // SPACE / CATEGORY 调用既有删除函数；409 时关闭确认框并打开迁移流程。
  setDeleteTarget(null);
}
```

- [ ] **Step 4: 渲染共享页头、Tabs、搜索与类型化列表**

```tsx
<div className="classification-page">
  <section className="classification-page-header">
    <div><h2>知识库分类管理</h2><p className="muted">维护知识库空间、部门与专题/项目。</p></div>
    <button onClick={openActiveCreate} type="button">{activeTabButtonLabel(activeTab)}</button>
  </section>
  <section className="classification-table-panel">
    <div className="classification-tabs-toolbar">
      <div aria-label="分类维度" role="tablist">
        <button aria-selected={activeTab === 'SPACE'} onClick={() => setActiveTab('SPACE')} role="tab" type="button">知识库空间</button>
        <button aria-selected={activeTab === 'DEPARTMENT'} onClick={() => setActiveTab('DEPARTMENT')} role="tab" type="button">部门</button>
        <button aria-selected={activeTab === 'CATEGORY'} onClick={() => setActiveTab('CATEGORY')} role="tab" type="button">专题 / 项目</button>
      </div>
      <label className="classification-search">
        搜索当前分类
        <input value={keyword} onChange={(event) => setKeyword(event.target.value)} />
      </label>
    </div>
    {activeTab === 'SPACE' ? renderSpaces() : null}
    {activeTab === 'DEPARTMENT' ? renderDepartments() : null}
    {activeTab === 'CATEGORY' ? renderCategories() : null}
  </section>
</div>
```

- [ ] **Step 5: 保留专题/项目的空间与部门范围筛选**

```tsx
{activeTab === 'CATEGORY' ? (
  <div className="classification-scope-filters">
    <label>
      知识库空间
      <select onChange={(event) => setSelectedSpaceId(event.target.value)} value={selectedSpaceId}>
        {spaces.map((space) => <option key={space.id} value={space.id}>{space.name}</option>)}
      </select>
    </label>
    <label>
      分类部门
      <select onChange={(event) => setSelectedDepartmentId(event.target.value)} value={selectedDepartmentId}>
        {departments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}
      </select>
    </label>
  </div>
) : null}
```

- [ ] **Step 6: 运行新增的 Playwright 分类场景**

Run: `python web\admin\tests\t09_knowledge_playwright.py`  
Expected: PASS，包含空间、部门、专题/项目的弹窗 CRUD、迁移和删除确认断言。

- [ ] **Step 7: 提交页面改动**

```bash
git add web/admin/src/features/knowledge/pages/KnowledgeClassificationPage.tsx
git commit -m "feat: redesign classification management page"
```

### Task 4: 添加参考稿风格与响应式布局

**Files:**
- Modify: `web/admin/src/styles.css`

- [ ] **Step 1: 添加分类页面、Tab、列表行和图标样式**

```css
.classification-table-panel {
  background: #ffffff;
  border: 1px solid #e4e9f2;
  border-radius: 8px;
  overflow: hidden;
}

.classification-tab[aria-selected='true'] {
  border-bottom: 2px solid #2d6df6;
  color: #2d6df6;
}

.classification-list-row {
  border-top: 1px solid #edf1f7;
  min-height: 62px;
}
```

- [ ] **Step 2: 添加紧凑表单与删除确认样式**

```css
.classification-delete-modal {
  max-width: 432px;
  text-align: center;
}

.delete-warning-icon {
  align-items: center;
  background: #ffeaed;
  border-radius: 12px;
  color: #ef4c58;
  display: inline-flex;
  height: 48px;
  justify-content: center;
  width: 48px;
}
```

- [ ] **Step 3: 增加窄屏布局规则**

```css
@media (max-width: 860px) {
  .classification-tabs-toolbar,
  .classification-page-header,
  .classification-scope-filters {
    align-items: stretch;
    flex-direction: column;
  }

  .classification-list-head {
    display: none;
  }

  .classification-list-row {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 4: 运行构建并检查格式**

Run: `npm run build` in `web/admin`  
Expected: PASS。

- [ ] **Step 5: 提交样式改动**

```bash
git add web/admin/src/styles.css
git commit -m "style: polish classification management ui"
```

### Task 5: 浏览器回归与最终验证

**Files:**
- Modify: `docs/development/v1.1/acceptance/t09-knowledge-classification-desktop.png`
- Modify: `docs/development/v1.1/acceptance/t09-knowledge-mobile.png`

- [ ] **Step 1: 启动 admin 开发服务器**

Run: `npm run dev -- --host 127.0.0.1 --port 5174` in `web/admin`  
Expected: Vite 在 `http://127.0.0.1:5174` 提供页面。

- [ ] **Step 2: 在桌面视口验证三个 Tab 和弹窗**

```python
desktop_page = browser.new_page(viewport={"width": 1440, "height": 900})
verify_classification_admin_flow(desktop_page, api)
desktop_page.screenshot(path=str(SCREENSHOT_DIR / "t09-knowledge-classification-desktop.png"), full_page=True)
```

- [ ] **Step 3: 在 390px 宽度验证无横向溢出**

```python
mobile_page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
mobile_page.goto(f"{APP_ORIGIN}/#knowledge-classification", wait_until="networkidle")
verify_no_overflow(mobile_page)
mobile_page.screenshot(path=str(SCREENSHOT_DIR / "t09-knowledge-mobile.png"), full_page=True)
```

- [ ] **Step 4: 运行最终命令**

Run: `npm run build` in `web/admin`  
Expected: PASS。

Run: `python web\admin\tests\t09_knowledge_playwright.py`  
Expected: PASS，且浏览器控制台不含 error 或 warning。

- [ ] **Step 5: 提交验收产物（若测试更新了受版本控制的截图）**

```bash
git add docs/development/v1.1/acceptance web/admin/tests/t09_knowledge_playwright.py
git commit -m "test: verify classification admin redesign"
```
