export type ApiKey = {
  id: string;
  name: string;
  keyPrefix: string;
  status: string;
  scopes: string[];
  allowedDepartmentIds: string[];
  allowedRoleIds: string[];
  rateLimitPerMinute: number;
  lastUsedAt: string | null;
  expiresAt: string | null;
  createdAt: string;
};

export type ApiKeyCreateResult = ApiKey & {
  key: string;
  warning: string;
};

export type ApiKeyCreatePayload = {
  name: string;
  scopes: string[];
  allowedDepartmentIds: string[];
  allowedRoleIds: string[];
  rateLimitPerMinute: number;
};

export type ApiCallLog = {
  id: string;
  keyPrefix: string | null;
  path: string;
  method: string;
  statusCode: number;
  latencyMs: number;
  errorCode: string | null;
  requestId: string | null;
  createdAt: string;
};
