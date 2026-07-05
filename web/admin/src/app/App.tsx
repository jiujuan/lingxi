import { LoginPage } from '../features/auth/LoginPage';
import { AppRoutes } from '../routes';

export function App() {
  const hasToken = Boolean(localStorage.getItem('lingxi_access_token'));

  if (!hasToken) {
    return <LoginPage />;
  }

  return <AppRoutes />;
}

