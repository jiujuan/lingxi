import { FormEvent, useState } from 'react';

import { apiRequest } from '../../api/client';
import type { TokenResponse } from '../../api/schema-helpers';
import { saveAuth } from '../../auth/authStore';

// Response shape comes straight from the generated OpenAPI contract.
type LoginResponse = TokenResponse;

export function LoginPage() {
  const [email, setEmail] = useState(import.meta.env.VITE_DEFAULT_LOGIN_EMAIL);
  const [password, setPassword] = useState(import.meta.env.VITE_DEFAULT_LOGIN_PASSWORD);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);

    try {
      const result = await apiRequest<LoginResponse>('/api/v1/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
        skipAuthRedirect: true,
      });
      saveAuth(result.accessToken, result.user);
      window.location.reload();
    } catch {
      setError('登录失败，请检查账号和密码。');
    }
  }

  return (
    <main className="login-page">
      <form onSubmit={submit}>
        <h1>Lingxi</h1>
        <p>企业级 AI 知识库系统</p>
        <label>
          账号
          <input value={email} onChange={(event) => setEmail(event.target.value)} />
        </label>
        <label>
          密码
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type="password"
          />
        </label>
        {error ? <div className="error">{error}</div> : null}
        <button type="submit">登录</button>
      </form>
    </main>
  );
}
