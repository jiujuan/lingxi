import { clearAuth, getToken, redirectToLogin } from '../auth/authStore';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

/** Normalised API error that preserves the backend error code and requestId. */
export class ApiError extends Error {
  status: number;
  code: string;
  requestId?: string;
  details?: unknown;

  constructor(
    status: number,
    code: string,
    message: string,
    requestId?: string,
    details?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }
}

type ApiRequestOptions = RequestInit & {
  /** Skip the automatic 401 -> logout redirect (used by the login call). */
  skipAuthRedirect?: boolean;
};

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const { skipAuthRedirect, ...init } = options;
  const headers = new Headers(init.headers);
  const token = getToken();

  if (!headers.has('Content-Type') && init.body) {
    headers.set('Content-Type', 'application/json');
  }
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  } catch {
    // Network failure / CORS: surface a clear error instead of a raw TypeError.
    throw new ApiError(0, 'NETWORK_ERROR', '网络异常，请检查连接后重试');
  }

  if (!response.ok) {
    const error = await toApiError(response);

    // An expired/invalid session (we had a token) should log the user out.
    // A 401 with no prior token is a failed login attempt — let it surface.
    if (response.status === 401 && token && !skipAuthRedirect) {
      redirectToLogin();
    } else if (response.status === 401) {
      clearAuth();
    }
    throw error;
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await parseBody(response)) as T;
}

async function parseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function toApiError(response: Response): Promise<ApiError> {
  const body = await parseBody(response);
  const fallback = `请求失败（HTTP ${response.status}）`;

  if (body && typeof body === 'object') {
    const payload = body as Record<string, unknown>;
    const err = payload.error as Record<string, unknown> | undefined;
    if (err && typeof err === 'object') {
      return new ApiError(
        response.status,
        String(err.code ?? 'REQUEST_ERROR'),
        String(err.message ?? fallback),
        (payload.requestId as string | undefined) ?? undefined,
        err.details,
      );
    }
    // FastAPI validation errors: { detail: [...] } or { detail: "..." }
    if ('detail' in payload) {
      const detail = payload.detail;
      const message = typeof detail === 'string' ? detail : '请求参数校验失败';
      return new ApiError(response.status, 'VALIDATION_ERROR', message);
    }
  }

  return new ApiError(
    response.status,
    'REQUEST_ERROR',
    typeof body === 'string' && body ? body : fallback,
  );
}

/** Best-effort human-readable message from any thrown value. */
export function errorMessage(error: unknown, fallback = '操作失败'): string {
  if (error instanceof ApiError) {
    return error.message || fallback;
  }
  if (error instanceof Error) {
    return error.message || fallback;
  }
  return fallback;
}
