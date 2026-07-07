export type Department = {
  id: string;
  name: string;
  code: string;
  parentId: string | null;
  userCount: number;
  createdAt: string;
};

export type DepartmentPayload = {
  name: string;
  code: string;
  parentId: string | null;
};

export type Role = {
  id: string;
  code: string;
  name: string;
};

export type AdminUser = {
  id: string;
  email: string;
  name: string;
  status: string;
  departmentId: string | null;
  departmentName: string | null;
  roles: Role[];
  createdAt: string;
};

export type UserPayload = {
  email: string;
  name: string;
  departmentId: string | null;
  roleIds: string[];
};

export type UserCreatePayload = UserPayload & { password: string };

export type UserListFilters = {
  keyword: string;
  departmentId: string;
  status: string;
  page: number;
  pageSize: number;
};

export type Pagination = {
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
};

export type UserListResult = {
  data: AdminUser[];
  pagination: Pagination;
};
