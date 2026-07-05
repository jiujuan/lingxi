# T15 日志、任务排障与可观测性页面

## 任务状态

- 状态：DONE
- 完成任务进度：100%
- 优先级：P1
- 预计范围：中

## Task 目标

实现系统管理员排障所需的日志与任务页面，串联 request_id、run_id、task_run_id，覆盖任务日志、模型调用日志、API 调用日志、审计日志、失败重试和敏感字段脱敏。

## 实现功能

- 任务日志列表和详情 API。
- 模型调用日志列表 API。
- API 调用日志列表 API。
- 审计日志列表 API。
- 日志筛选：时间、状态、任务类型、文档、用户、request_id、run_id、task_run_id。
- 任务详情展示阶段、耗时、错误码、错误摘要、retryable。
- 可重试任务展示重试 API。
- 模型调用日志展示供应商、模型、能力、耗时、Token 用量、错误码。
- API 调用日志展示 key 前缀、path、状态码、耗时、错误码。
- 审计日志展示操作人、动作、资源、before/after 摘要和 request_id。
- 日志脱敏规则，过滤 API Key、模型密钥、Authorization header。
- 前端日志与任务页面，支持 Tab、筛选、分页、复制 request_id。
- 从文档详情、Chat run、API Key 页面跳转到相关日志。

## 修改或增加文件

- `server/app/api/routes/logs.py`
- `server/app/api/routes/task_runs.py`
- `server/app/services/log_query_service.py`
- `server/app/services/task_retry_service.py`
- `server/app/core/log_redaction.py`
- `server/app/repositories/task_run_repository.py`
- `server/app/repositories/model_call_log_repository.py`
- `server/app/repositories/audit_log_repository.py`
- `server/app/schemas/logs.py`
- `web/src/pages/logs/LogsPage.tsx`
- `web/src/pages/logs/TaskRunTable.tsx`
- `web/src/pages/logs/ModelCallLogTable.tsx`
- `web/src/pages/logs/ApiCallLogTable.tsx`
- `web/src/pages/logs/AuditLogTable.tsx`
- `web/src/pages/logs/LogDetailDrawer.tsx`
- `web/src/api/logs.ts`
- `web/src/types/logs.ts`
- `server/app/tests/api/test_logs.py`
- `server/app/tests/security/test_log_redaction.py`
- `web/src/tests/e2e/logs-observability.spec.ts`

## 不修改范围

- 不引入完整分布式追踪平台。
- 不实现日志长期归档和分区迁移。
- 不展示敏感字段明文。
- 不把普通应用日志作为业务审计来源。
- 不实现复杂报表，Dashboard 汇总由 T16 完成。

## 涉及其它 Task

- 依赖 T05/T06/T07/T08 的任务运行记录。
- 依赖 T11/T12 的 run_id、query_runs 和引用链路。
- 依赖 T13/T14 的 API 调用日志。
- T16 复用日志聚合指标。
- T17 验证 request_id、run_id、task_run_id 链路和脱敏规则。

## 测试策略

- 测试日志列表分页和筛选。
- 测试按 request_id、run_id、task_run_id 查询。
- 测试可重试任务返回重试入口，不可重试任务返回原因。
- 测试敏感字段脱敏，包括 API Key、模型密钥、Authorization header。
- 测试普通用户无权访问日志页面。
- 前端测试日志 Tab、筛选、分页、详情抽屉和复制功能。
- 构造失败任务，验证日志页可完成排障闭环。

## 长任务链路验收策略

制造一次文档解析失败、一次模型调用失败和一次 API Key 调用失败，分别从文档详情、Chat 回答、API Key 页面跳转到日志页，确认能通过 request_id、run_id、task_run_id 追踪到错误阶段、错误码、耗时和可重试状态，且所有 Secret 均已脱敏。

## 验收功能清单

- [x] 任务日志列表和详情可用。
- [x] 模型调用日志列表可用。
- [x] API 调用日志列表可用。
- [x] 审计日志列表可用。
- [x] 日志支持 request_id、run_id、task_run_id 查询。
- [x] 可重试任务能从日志页触发重试。
- [x] 日志页展示错误码、错误摘要和耗时。
- [x] 敏感字段脱敏测试通过。
- [x] 前端日志页面支持筛选、分页、详情抽屉。
- [x] 从核心页面可跳转到相关日志。

## 验收结果

- 已完成。
- 后端新增日志查询、任务重试、日志脱敏模块和 API：
  - `GET /api/v1/logs/task-runs`
  - `GET /api/v1/logs/task-runs/{task_run_id}`
  - `POST /api/v1/task-runs/{task_run_id}/retry`
  - `GET /api/v1/logs/model-calls`
  - `GET /api/v1/logs/api-calls`
  - `GET /api/v1/logs/audit`
- 前端新增 `#logs` 日志排障页面，支持 Tab、筛选、复制 request_id、详情抽屉和任务重试。
- 已从文档处理日志、Chat message request_id、API Key 页面接入日志页跳转。
- 敏感字段脱敏覆盖 `apiKey`、`Authorization`、`secret`、`encrypted_api_key` 等字段，同时保留安全的 `keyPrefix`。
- 验证命令：
  - `python -m pytest server\tests\test_log_redaction.py server\tests\test_logs_observability.py server\tests\test_dashboard_settings.py`：5 passed
  - `python -m pytest server\tests`：60 passed
  - `npm run build`：passed

## 完成任务进度

100%
