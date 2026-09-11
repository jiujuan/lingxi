# Admin Sidebar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh the authenticated admin sidebar to match the approved visual reference without changing the existing route or permission model.

**Architecture:** Keep the route table as the single source of truth and extend each route with an icon identifier. Render a structured brand header, icon-and-label navigation links, and a static administrator profile block from `AppRoutes`. Use the existing global stylesheet for all visual changes so no new package is required.

**Tech Stack:** React 19, TypeScript, Vite, global CSS.

---

### Task 1: Add Sidebar Structure And Icons

**Files:**
- Modify: `web/admin/src/routes/index.tsx`

- [ ] **Step 1: Add a route icon type and inline icon renderer**

```tsx
type RouteIcon =
  | 'dashboard'
  | 'knowledge'
  | 'folder'
  | 'chat'
  | 'logs'
  | 'key'
  | 'models'
  | 'departments'
  | 'users'
  | 'settings';

function SidebarIcon({ name }: { name: RouteIcon }) {
  return <svg aria-hidden="true" className="sidebar-icon" viewBox="0 0 24 24">...</svg>;
}
```

- [ ] **Step 2: Add an icon property to every route**

```tsx
{
  hash: '#dashboard',
  icon: 'dashboard',
  label: '总览',
  permission: 'DASHBOARD_READ',
  render: () => <DashboardPage />,
}
```

- [ ] **Step 3: Replace the plain sidebar heading with branded header and profile markup**

```tsx
<aside className="sidebar">
  <div className="sidebar-brand">
    <div aria-hidden="true" className="sidebar-brand-mark">L</div>
    <div>
      <strong>灵犀</strong>
      <span>企业 AI 知识库</span>
    </div>
  </div>
  <nav aria-label="主导航">...</nav>
  <div className="sidebar-profile">...</div>
</aside>
```

- [ ] **Step 4: Render each permitted route with its icon**

```tsx
<a className={routeHash === route.hash ? 'active' : ''} href={route.hash} key={route.hash}>
  <SidebarIcon name={route.icon} />
  <span>{route.label}</span>
</a>
```

### Task 2: Style The Sidebar

**Files:**
- Modify: `web/admin/src/styles.css`

- [ ] **Step 1: Set the approved shell and sidebar dimensions**

```css
.shell {
  grid-template-columns: 220px minmax(0, 1fr);
}

.sidebar {
  display: flex;
  flex-direction: column;
  padding: 0;
}
```

- [ ] **Step 2: Add brand, navigation, icon, and profile visual styles**

```css
.sidebar a {
  align-items: center;
  display: flex;
  font-size: 14px;
  font-weight: 500;
  gap: 12px;
  min-height: 36px;
}

.sidebar-icon {
  flex: 0 0 16px;
  height: 16px;
  width: 16px;
}
```

- [ ] **Step 3: Preserve the narrow-screen one-column shell**

```css
@media (max-width: 860px) {
  .sidebar {
    border-bottom: 1px solid #e4e9f2;
    border-right: 0;
  }
}
```

### Task 3: Verify The Frontend

**Files:**
- Verify: `web/admin/src/routes/index.tsx`
- Verify: `web/admin/src/styles.css`

- [ ] **Step 1: Run the production build**

Run: `npm run build`

Expected: `tsc --noEmit && vite build` completes successfully.

- [ ] **Step 2: Inspect the working diff**

Run: `git diff --check`

Expected: no output.

- [ ] **Step 3: Commit the implementation**

```bash
git add web/admin/src/routes/index.tsx web/admin/src/styles.css
git commit -m "feat: refresh admin sidebar"
```
