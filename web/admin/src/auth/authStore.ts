export type AuthUser = {
  id: string;
  email: string;
  name: string;
  roles: string[];
  permissions: string[];
};

export function saveAuth(accessToken: string, user: AuthUser) {
  localStorage.setItem('lingxi_access_token', accessToken);
  localStorage.setItem('lingxi_user', JSON.stringify(user));
}

export function currentUser(): AuthUser | null {
  const raw = localStorage.getItem('lingxi_user');
  return raw ? (JSON.parse(raw) as AuthUser) : null;
}

