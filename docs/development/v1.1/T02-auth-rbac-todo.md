# T02 登录、用户与 RBAC 权限底座

## 任务状态

- 状态：IN_PROGRESS
- 完成任务进度：85%
- 优先级：P0
- 预计范围：中

## Task 目标

实现后台登录、Token、当前用户、部门、角色、权限码和审计上下文，为文档权限过滤、菜单权限和 API 权限校验提供基础。

## 实现功能

- 用户、部门、角色、权限、用户角色、角色权限模型和迁移。
- 初始系统管理员、知识管理员、员工角色和权限码 seed。
- 登录、刷新 Token、登出、当前用户接口。
- 密码安全哈希。
- Access Token 和 Refresh Token 基础策略。
- 权限依赖函数和 `AccessContext`。
- 前端登录页、权限缓存和权限路由。

## 修改或增加文件

- `server/app/models/user.py`
- `server/app/models/role.py`
- `server/app/models/permission.py`
- `server/app/core/security.py`
- `server/app/core/permissions.py`
- `server/app/services/auth_service.py`
- `server/app/services/user_access_service.py`
- `server/app/api/v1/auth.py`
- `server/app/schemas/auth.py`
- `web/admin/src/auth/authStore.ts`
- `web/admin/src/auth/PermissionGate.tsx`
- `web/admin/src/features/auth/LoginPage.tsx`

## 不修改范围

- 不实现文档级访问规则。
- 不实现完整用户管理 UI。
- 不实现 SSO、LDAP、企业微信登录。

## 涉及其它 Task

- 依赖 T01。
- T03 使用用户、角色和权限表。
- T09-T16 使用前端权限缓存和 PermissionGate。

## 测试策略

- 登录成功、失败和禁用用户测试。
- Token refresh 测试。
- 权限码返回测试。
- 前端无权限路由测试。
- 密码 hash 不明文保存测试。

## 长任务链路验收策略

创建 seed 管理员，完成登录，前端拿到当前用户和权限码，访问受保护接口成功，缺少权限时返回 403。

## 验收功能清单

- [x] 用户、角色、权限迁移可执行。
- [x] seed 角色和权限码可生成。
- [x] 登录接口可用。
- [x] Refresh Token 接口可用。
- [x] 登出接口可用。
- [x] 当前用户接口返回部门、角色、权限。
- [x] 权限不足返回统一 403。
- [ ] 前端能根据权限显示完整导航。
- [x] 密码不明文落库。

## 验收结果

- 已实现用户、部门、角色、权限、用户角色、角色权限模型；已实现 seed 管理员和员工账号；已实现登录、刷新 Token、登出、当前用户和权限校验接口。
- 已实现 bcrypt 密码哈希，测试确认密码不明文落库。
- 已实现前端登录页、authStore 和 PermissionGate 骨架；完整权限导航将在 T09/T16 页面落地时继续完善。
- 验证通过：`python -m pytest server\tests\test_auth_rbac.py`，4 passed。

## 完成任务进度

85%
