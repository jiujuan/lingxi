export type RolePermission = {
  id: string;
  code: string;
  module: string;
  action: string;
  description: string | null;
};

export type Role = {
  id: string;
  name: string;
  code: string;
  scope: string;
  isBuiltin: boolean;
  userCount: number;
  permissionCount: number;
  createdAt: string;
};

export type RoleDetail = Role & {
  permissions: RolePermission[];
};

export type RolePayload = {
  name: string;
  code: string;
  permissionIds: string[];
};

export type RoleListFilters = {
  keyword: string;
  page: number;
  pageSize: number;
};

export type Pagination = {
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
};

export type RoleListResult = {
  data: Role[];
  pagination: Pagination;
};
