import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';

import { hasPermission } from '../auth/authStore';
import { ApiKeyPage } from '../features/api-keys/pages/ApiKeyPage';
import { ChatPage } from '../features/chat/pages/ChatPage';
import { DashboardPage } from '../features/dashboard/pages/DashboardPage';
import { ImportPage } from '../features/knowledge/pages/ImportPage';
import { LogsPage } from '../features/logs/pages/LogsPage';
import { ModelConfigPage } from '../features/model-config/pages/ModelConfigPage';
import { SettingsPage } from '../features/settings/pages/SettingsPage';

type Route = {
  hash: string;
  label: string;
  permission: string;
  render: () => ReactNode;
};

// Each route declares the "read" permission that gates its menu entry.
const ROUTES: Route[] = [
  {
    hash: '#dashboard',
    label: '总览',
    permission: 'DASHBOARD_READ',
    render: () => <DashboardPage />,
  },
  {
    hash: '#knowledge',
    label: '知识库中心',
    permission: 'DOCUMENT_READ',
    render: () => <ImportPage />,
  },
  { hash: '#chat', label: 'Chat', permission: 'CHAT_READ', render: () => <ChatPage /> },
  { hash: '#logs', label: '日志排障', permission: 'LOG_READ', render: () => <LogsPage /> },
  { hash: '#api-keys', label: 'API Key', permission: 'API_KEY_READ', render: () => <ApiKeyPage /> },
  {
    hash: '#models',
    label: '模型配置',
    permission: 'MODEL_CONFIG_READ',
    render: () => <ModelConfigPage />,
  },
  {
    hash: '#settings',
    label: '系统设置',
    permission: 'SETTING_READ',
    render: () => <SettingsPage />,
  },
];

export function AppRoutes() {
  const visibleRoutes = ROUTES.filter((route) => hasPermission(route.permission));
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
        <h1>Lingxi</h1>
        <nav>
          {visibleRoutes.map((route) => (
            <a
              className={routeHash === route.hash ? 'active' : ''}
              href={route.hash}
              key={route.hash}
            >
              {route.label}
            </a>
          ))}
        </nav>
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
