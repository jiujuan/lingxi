const TOKEN_KEY = 'lingxi_access_token';
const USER_KEY = 'lingxi_user';

export type AuthUser = {
  id: string;
  email: string;
  name: string;
  roles: string[];
  permissions: string[];
};

export function saveAuth(accessToken: string, user: AuthUser) {
  localStorage.setItem(TOKEN_KEY, accessToken);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function currentUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    // Corrupted/tampered storage must not white-screen the app.
    clearAuth();
    return null;
  }
}

export function permissions(): string[] {
  return currentUser()?.permissions ?? [];
}

export function hasPermission(permission: string): boolean {
  return permissions().includes(permission);
}

/** Clear the session and return to the login screen (e.g. after a 401). */
export function redirectToLogin() {
  clearAuth();
  if (window.location.hash) {
    window.location.hash = '';
  }
  window.location.reload();
}
