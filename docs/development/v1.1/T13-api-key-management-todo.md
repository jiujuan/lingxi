# T13 API Key 管理、限流与调用日志

## 任务状态

- 状态：DONE
- 完成任务进度：100%
- 优先级：P1
- 预计范围：中

## Task 目标

实现内部系统调用所需的 API Key 管理能力，包括创建、明文只展示一次、hash 存储、禁用、轮换、Scope、权限范围、限流、审计日志和调用日志基础能力。

## 实现功能

- API Key 创建 API。
- API Key 列表 API，只返回前缀、状态、Scope、最近使用时间。
- API Key 禁用 API。
- API Key 轮换 API，新明文只展示一次。
- Key 生成、prefix 截取和 hash 校验。
- API Key Scope 校验。
- API Key 绑定部门、角色权限范围。
- 每分钟限流规则。
- API Key 操作写入审计日志。
- API 调用日志写入 `api_call_logs`。
- API Key 前端页面：列表、创建、禁用、轮换、Scope、限流、调用示例。
- 禁用和轮换二次确认。
- 示例代码隐藏真实 Key。

## 修改或增加文件

- `server/app/api/routes/api_keys.py`
- `server/app/core/api_key_security.py`
- `server/app/services/api_key_service.py`
- `server/app/services/rate_limit_service.py`
- `server/app/repositories/api_key_repository.py`
- `server/app/repositories/api_call_log_repository.py`
- `server/app/schemas/api_key.py`
- `server/app/middlewares/api_key_auth.py`
- `web/src/pages/api-keys/ApiKeyPage.tsx`
- `web/src/pages/api-keys/ApiKeyCreateModal.tsx`
- `web/src/pages/api-keys/ApiKeyRotateModal.tsx`
- `web/src/pages/api-keys/ApiCallLogTable.tsx`
- `web/src/api/apiKeys.ts`
- `web/src/types/apiKey.ts`
- `server/app/tests/api/test_api_keys.py`
- `server/app/tests/security/test_api_key_security.py`
- `web/src/tests/e2e/api-key-management.spec.ts`

## 不修改范围

- 不实现 `/v1/chat/completions` 业务接口。
- 不实现 API Key 多租户计费或套餐。
- 不支持明文 Key 再次查看。
- 不把 API Key 明文、Authorization header 或完整 Token 写入日志。
- 不做复杂 IP 白名单，V1.1 只预留配置字段。

## 涉及其它 Task

- 依赖 T02 的用户、角色、权限和审计上下文。
- 依赖 T03 的 API Key、API 调用日志和审计表。
- T14 使用本任务的 API Key 认证、Scope、限流和权限范围。
- T15 展示 API 调用日志并按 request_id 排障。
- T17 验证密钥不泄露和限流行为。

## 测试策略

- 测试创建 API Key 只在创建响应返回明文。
- 测试数据库只保存 key_hash 和 key_prefix。
- 测试错误 Key、禁用 Key、过期 Key 返回 401。
- 测试 Scope 不足返回 403。
- 测试限流超限返回 429。
- 测试禁用和轮换写审计日志。
- 测试调用日志不包含明文 Key 和 Authorization header。
- 前端测试创建弹窗关闭后无法再次查看明文。

## 长任务链路验收策略

系统管理员创建一个 API Key，复制明文后刷新页面确认只展示前缀；使用该 Key 调用一个受保护的测试端点，确认认证、Scope、限流和调用日志生效；禁用 Key 后再次调用返回 401；轮换 Key 后旧 Key 立即失效，新 Key 可用。

## 验收功能清单

- [x] API Key 可创建。
- [x] 明文 Key 只展示一次。
- [x] 数据库不保存明文 Key。
- [x] API Key 列表只展示前缀和状态。
- [x] API Key 可禁用并立即失效。
- [x] API Key 可轮换，旧 Key 默认立即失效。
- [x] Scope 校验可用。
- [x] 限流可返回 429。
- [x] API 调用日志记录 request_id、key 前缀、状态码和耗时。
- [x] 审计日志覆盖创建、禁用、轮换操作。

## 验收结果

- 已完成。
- 后端验证：`python -m pytest server\tests`，结果 `49 passed`。
- 前端构建：`npm run build`，结果 Vite build 成功。
- 浏览器验收：`python web\admin\tests\t13_api_key_playwright.py`，结果通过。
- 验收截图：
  - `docs/development/v1.1/acceptance/t13-api-key-desktop.png`
  - `docs/development/v1.1/acceptance/t13-api-key-mobile.png`

## 完成任务进度

100%
