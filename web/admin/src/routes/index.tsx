import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';

import { currentUser, hasPermission } from '../auth/authStore';
import { ApiKeyPage } from '../features/api-keys/pages/ApiKeyPage';
import { ChatPage } from '../features/chat/pages/ChatPage';
import { DashboardPage } from '../features/dashboard/pages/DashboardPage';
import { DocumentListPage } from '../features/knowledge/pages/DocumentListPage';
import { DocumentManagementDetailPage } from '../features/knowledge/pages/DocumentManagementDetailPage';
import { DocumentManagementPage } from '../features/knowledge/pages/DocumentManagementPage';
import { ImportPage } from '../features/knowledge/pages/ImportPage';
import { KnowledgeClassificationPage } from '../features/knowledge/pages/KnowledgeClassificationPage';
import { LogsPage } from '../features/logs/pages/LogsPage';
import { ModelConfigPage } from '../features/model-config/pages/ModelConfigPage';
import { DepartmentPage } from '../features/org/pages/DepartmentPage';
import { UserPage } from '../features/org/pages/UserPage';
import { SettingsPage } from '../features/settings/pages/SettingsPage';

type Route = {
  hash: string;
  icon: SidebarIconName;
  label: string;
  permission: string;
  render: () => ReactNode;
  /** Reachable by hash but not listed in the sidebar (entered from in-page buttons). */
  hidden?: boolean;
};

type SidebarIconName =
  | 'dashboard'
  | 'knowledge'
  | 'document'
  | 'classification'
  | 'chat'
  | 'logs'
  | 'key'
  | 'model'
  | 'department'
  | 'users'
  | 'settings';

function SidebarIcon({ name }: { name: SidebarIconName }) {
  const commonProps = {
    fill: 'none',
    stroke: 'currentColor',
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    strokeWidth: 1.7,
  };

  switch (name) {
    case 'dashboard':
      return (
        <svg aria-hidden="true" className="sidebar-icon" viewBox="0 0 24 24">
          <rect {...commonProps} x="4" y="4" width="6" height="6" rx="1" />
          <rect {...commonProps} x="14" y="4" width="6" height="6" rx="1" />
          <rect {...commonProps} x="4" y="14" width="6" height="6" rx="1" />
          <rect {...commonProps} x="14" y="14" width="6" height="6" rx="1" />
        </svg>
      );
    case 'knowledge':
      return (
        <svg aria-hidden="true" className="sidebar-icon" viewBox="0 0 24 24">
          <path {...commonProps} d="M12 4v8m0 0 3-3m-3 3L9 9M5 16h14v4H5z" />
        </svg>
      );
    case 'document':
      return (
        <svg aria-hidden="true" className="sidebar-icon" viewBox="0 0 24 24">
          <path {...commonProps} d="M5 3h9l5 5v13H5zM14 3v6h6M8 13h8M8 17h6" />
        </svg>
      );
    case 'classification':
      return (
        <svg aria-hidden="true" className="sidebar-icon" viewBox="0 0 24 24">
          <path
            {...commonProps}
            d="M4 5.5A2.5 2.5 0 0 1 6.5 3H11v16H6.5A2.5 2.5 0 0 1 4 16.5zM20 5.5A2.5 2.5 0 0 0 17.5 3H13v16h4.5a2.5 2.5 0 0 0 2.5-2.5z"
          />
        </svg>
      );
    case 'chat':
      return (
        <svg aria-hidden="true" className="sidebar-icon" viewBox="0 0 24 24">
          <path {...commonProps} d="M5 5h14v10H9l-4 4z" />
          <path {...commonProps} d="M9 9h6M9 12h3" />
        </svg>
      );
    case 'logs':
      return (
        <svg aria-hidden="true" className="sidebar-icon" viewBox="0 0 24 24">
          <path {...commonProps} d="M4 17 9 12l3 3 7-8M4 21h16" />
        </svg>
      );
    case 'key':
      return (
        <svg aria-hidden="true" className="sidebar-icon" viewBox="0 0 24 24">
          <circle {...commonProps} cx="8" cy="15" r="4" />
          <path {...commonProps} d="m11 12 8-8m-3 0h3v3m-6 0h3v3" />
        </svg>
      );
    case 'model':
      return (
        <svg aria-hidden="true" className="sidebar-icon" viewBox="0 0 24 24">
          <path {...commonProps} d="m12 3 7 4-7 4-7-4 7-4ZM5 12l7 4 7-4M5 17l7 4 7-4" />
        </svg>
      );
    case 'department':
      return (
        <svg aria-hidden="true" className="sidebar-icon" viewBox="0 0 24 24">
          <path {...commonProps} d="M4 20V6h10v14M14 10h6v10M8 10h2m-2 4h2m6 0h1" />
        </svg>
      );
    case 'users':
      return (
        <svg aria-hidden="true" className="sidebar-icon" viewBox="0 0 24 24">
          <circle {...commonProps} cx="9" cy="8" r="3" />
          <path {...commonProps} d="M3 20a6 6 0 0 1 12 0M16 5a3 3 0 0 1 0 6M17 14a5 5 0 0 1 4 5" />
        </svg>
      );
    case 'settings':
      return (
        <svg aria-hidden="true" className="sidebar-icon" viewBox="0 0 24 24">
          <path {...commonProps} d="M4 7h16M4 12h16M4 17h16M8 4v6m8-6v6m-8 4v6m8-6v6" />
        </svg>
      );
  }
}

// Each route declares the "read" permission that gates its menu entry.
const ROUTES: Route[] = [
  {
    hash: '#dashboard',
    icon: 'dashboard',
    label: '总览',
    permission: 'DASHBOARD_READ',
    render: () => <DashboardPage />,
  },
  {
    hash: '#knowledge',
    icon: 'knowledge',
    label: '文档解析中心',
    permission: 'DOCUMENT_READ',
    render: () => <ImportPage />,
  },
  {
    hash: '#document-management',
    icon: 'document',
    label: '文档管理',
    permission: 'DOCUMENT_READ',
    render: () => <DocumentManagementPage />,
  },
  {
    hash: '#document-management-detail',
    icon: 'document',
    label: '文档详情',
    permission: 'DOCUMENT_READ',
    render: () => <DocumentManagementDetailPage />,
    hidden: true,
  },
  {
    hash: '#documents',
    icon: 'document',
    label: '文档列表',
    permission: 'DOCUMENT_READ',
    render: () => <DocumentListPage />,
    hidden: true,
  },
  {
    hash: '#knowledge-classification',
    icon: 'classification',
    label: '知识库分类',
    permission: 'DOCUMENT_READ',
    render: () => <KnowledgeClassificationPage />,
  },
  {
    hash: '#chat',
    icon: 'chat',
    label: 'Chat',
    permission: 'CHAT_READ',
    render: () => <ChatPage />,
  },
  {
    hash: '#logs',
    icon: 'logs',
    label: '日志排障',
    permission: 'LOG_READ',
    render: () => <LogsPage />,
  },
  {
    hash: '#api-keys',
    icon: 'key',
    label: 'API Key',
    permission: 'API_KEY_READ',
    render: () => <ApiKeyPage />,
  },
  {
    hash: '#models',
    icon: 'model',
    label: '模型配置',
    permission: 'MODEL_CONFIG_READ',
    render: () => <ModelConfigPage />,
  },
  {
    hash: '#departments',
    icon: 'department',
    label: '部门管理',
    permission: 'USER_READ',
    render: () => <DepartmentPage />,
  },
  {
    hash: '#users',
    icon: 'users',
    label: '用户管理',
    permission: 'USER_READ',
    render: () => <UserPage />,
  },
  {
    hash: '#settings',
    icon: 'settings',
    label: '系统设置',
    permission: 'SETTING_READ',
    render: () => <SettingsPage />,
  },
];

export function AppRoutes() {
  const user = currentUser();
  const visibleRoutes = ROUTES.filter(
    (route) => !route.hidden && hasPermission(route.permission),
  );
  const defaultHash = visibleRoutes[0]?.hash ?? '#dashboard';

  const [hash, setHash] = useState(window.location.hash || defaultHash);
  const routeHash = hash.split('?')[0] || defaultHash;

  useEffect(() => {
    const listener = () => setHash(window.location.hash || defaultHash);
    window.addEventListener('hashchange', listener);
    return () => window.removeEventListener('hashchange', listener);
  }, [defaultHash]);

  const active = ROUTES.find((route) => route.hash === routeHash);
  const permitted = active ? hasPermission(active.permission) : false;

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div aria-hidden="true" className="sidebar-brand-mark">
            L
          </div>
          <div>
            <strong>灵犀</strong>
            <span>企业 AI 知识库</span>
          </div>
        </div>
        <nav aria-label="主导航">
          {visibleRoutes.map((route) => (
            <a
              className={routeHash === route.hash ? 'active' : ''}
              href={route.hash}
              key={route.hash}
            >
              <SidebarIcon name={route.icon} />
              <span>{route.label}</span>
            </a>
          ))}
        </nav>
        <div className="sidebar-profile">
          <div aria-hidden="true" className="sidebar-avatar">
            {(user?.name || user?.email || '管').slice(0, 1).toUpperCase()}
          </div>
          <div>
            <strong>{user?.name || '管理员'}</strong>
            <span>{user?.roles[0] || '系统管理员'}</span>
          </div>
        </div>
      </aside>
      <section className="content">
        {permitted && active ? (
          active.render()
        ) : (
          <div className="panel empty-state">
            <strong>无权访问</strong>
            <p>你没有查看该模块的权限，请联系管理员分配相应角色。</p>
          </div>
        )}
      </section>
    </main>
  );
}
