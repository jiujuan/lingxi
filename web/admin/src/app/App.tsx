import { getToken } from '../auth/authStore';
import { LoginPage } from '../features/auth/LoginPage';
import { AppRoutes } from '../routes';

export function App() {
  const hasToken = Boolean(getToken());

  if (!hasToken) {
    return <LoginPage />;
  }

  return <AppRoutes />;
}

