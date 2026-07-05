import { useEffect, useState } from 'react';

import { ApiKeyPage } from '../features/api-keys/pages/ApiKeyPage';
import { ChatPage } from '../features/chat/pages/ChatPage';
import { DashboardPage } from '../features/dashboard/pages/DashboardPage';
import { ImportPage } from '../features/knowledge/pages/ImportPage';
import { LogsPage } from '../features/logs/pages/LogsPage';
import { ModelConfigPage } from '../features/model-config/pages/ModelConfigPage';
import { SettingsPage } from '../features/settings/pages/SettingsPage';

const ROUTES = [
  { hash: '#dashboard', label: '总览' },
  { hash: '#knowledge', label: '知识库中心' },
  { hash: '#chat', label: 'Chat' },
  { hash: '#logs', label: '日志排障' },
  { hash: '#api-keys', label: 'API Key' },
  { hash: '#models', label: '模型配置' },
  { hash: '#settings', label: '系统设置' },
];

export function AppRoutes() {
  const [hash, setHash] = useState(window.location.hash || '#dashboard');
  const routeHash = hash.split('?')[0] || '#dashboard';

  useEffect(() => {
    const listener = () => setHash(window.location.hash || '#dashboard');
    window.addEventListener('hashchange', listener);
    return () => window.removeEventListener('hashchange', listener);
  }, []);

  return (
    <main className="shell">
      <aside className="sidebar">
        <h1>Lingxi</h1>
        <nav>
          {ROUTES.map((route) => (
            <a className={routeHash === route.hash ? 'active' : ''} href={route.hash} key={route.hash}>
              {route.label}
            </a>
          ))}
        </nav>
      </aside>
      <section className="content">
        {routeHash === '#knowledge' ? <ImportPage /> : null}
        {routeHash === '#chat' ? <ChatPage /> : null}
        {routeHash === '#logs' ? <LogsPage /> : null}
        {routeHash === '#api-keys' ? <ApiKeyPage /> : null}
        {routeHash === '#models' ? <ModelConfigPage /> : null}
        {routeHash === '#settings' ? <SettingsPage /> : null}
        {routeHash === '#dashboard' ? <DashboardPage /> : null}
      </section>
    </main>
  );
}
