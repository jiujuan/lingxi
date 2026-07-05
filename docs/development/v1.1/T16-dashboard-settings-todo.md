# T16 总览 Dashboard 与系统设置

## 任务状态

- 状态：DONE
- 完成任务进度：100%
- 优先级：P1
- 预计范围：中

## Task 目标

实现系统总览和系统设置页面，让管理员能查看 MVP 关键健康指标，并配置文件限制、默认解析策略、检索参数、低置信阈值、限流策略、对象存储和数据保留策略。

## 实现功能

- Dashboard 汇总 API：文档数、QA 对数、任务成功率、失败率、API 调用量。
- 文档入库健康 API：上传、解析、QA、Embedding 阶段成功率和失败趋势。
- 问答健康 API：引用覆盖率、拒答率、命中率、首字响应耗时。
- 最近任务和风险事件 API。
- Dashboard 前端指标卡、趋势图、最近事件列表。
- 指标点击跳转到文档、日志或任务列表并带筛选条件。
- 系统设置读取和保存 API。
- 设置项：文件大小、允许类型、默认解析器、OCR、fallback、检索 TopK、低置信阈值、限流、数据保留。
- 高风险设置变更二次确认。
- 设置变更写审计日志。
- 设置变更后标明生效范围：新任务、新会话或立即生效。
- 前端设置页面表单校验、保存失败保留输入。

## 修改或增加文件

- `server/app/api/routes/dashboard.py`
- `server/app/api/routes/settings.py`
- `server/app/services/dashboard_service.py`
- `server/app/services/settings_service.py`
- `server/app/repositories/dashboard_repository.py`
- `server/app/repositories/system_setting_repository.py`
- `server/app/schemas/dashboard.py`
- `server/app/schemas/settings.py`
- `web/src/pages/dashboard/DashboardPage.tsx`
- `web/src/pages/dashboard/MetricCard.tsx`
- `web/src/pages/dashboard/HealthTrendChart.tsx`
- `web/src/pages/settings/SettingsPage.tsx`
- `web/src/pages/settings/FilePolicyForm.tsx`
- `web/src/pages/settings/RetrievalPolicyForm.tsx`
- `web/src/pages/settings/RetentionPolicyForm.tsx`
- `web/src/api/dashboard.ts`
- `web/src/api/settings.ts`
- `web/src/types/dashboard.ts`
- `web/src/types/settings.ts`
- `server/app/tests/api/test_dashboard.py`
- `server/app/tests/api/test_settings.py`
- `web/src/tests/e2e/dashboard-settings.spec.ts`

## 不修改范围

- 不实现完整 BI 报表系统。
- 不实现租户计费、套餐、发票或商业后台。
- 不做日志月度归档的实际迁移任务。
- 不直接修改历史任务结果。
- 不让前端设置绕过后端校验。

## 涉及其它 Task

- 依赖 T09 的知识库中心跳转目标。
- 依赖 T15 的日志和任务聚合数据。
- 使用 T03 的 system_settings 表。
- T05 上传页读取文件限制设置。
- T10/T11 读取检索阈值、TopK 和限流设置。
- T17 验证关键指标和设置变更审计。

## 测试策略

- 测试 Dashboard 指标在无数据时返回 0 和空列表。
- 测试时间范围筛选影响指标。
- 测试设置读取、保存、校验和审计日志。
- 测试非法阈值、非法文件大小、非法保留周期返回 422。
- 前端测试指标卡点击跳转并带筛选参数。
- 前端测试设置保存失败保留输入。
- 使用 mock 图表数据验证趋势图无重叠和空状态。

## 长任务链路验收策略

导入若干成功和失败任务、完成几次 Chat 和 API 调用后进入 Dashboard，确认核心指标、趋势和最近事件能反映真实数据；修改低置信阈值和文件大小限制，确认审计日志记录变更，并且新上传和新会话读取新设置。

## 验收功能清单

- [x] Dashboard 汇总指标 API 可用。
- [x] 入库健康指标可展示。
- [x] 问答健康指标可展示。
- [x] 最近任务和风险事件可展示。
- [x] 指标卡可跳转到对应列表。
- [x] 系统设置可读取和保存。
- [x] 高风险设置变更有二次确认。
- [x] 设置变更写入审计日志。
- [x] 非法设置返回字段级错误。
- [x] 设置页面保存失败不清空输入。

## 验收结果

- 已完成。
- 后端新增 Dashboard 和 Settings API：
  - `GET /api/v1/dashboard/summary`
  - `GET /api/v1/dashboard/ingestion-health`
  - `GET /api/v1/dashboard/qa-health`
  - `GET /api/v1/dashboard/recent-activity`
  - `GET /api/v1/settings`
  - `PUT /api/v1/settings`
- 前端新增 `#dashboard` 系统总览页面和 `#settings` 系统设置页面。
- Dashboard 展示文档数、QA 对数、任务成功/失败率、API 调用量、入库健康、问答健康、最近任务和风险事件。
- Settings 支持文件策略、检索策略、限流策略、对象存储和数据保留策略；高风险保存前二次确认，保存失败保留当前输入。
- 设置变更写入 `audit_logs`，非法阈值、文件大小、保留周期由后端 Pydantic 字段级校验返回 422。
- 验证命令：
  - `python -m pytest server\tests\test_log_redaction.py server\tests\test_logs_observability.py server\tests\test_dashboard_settings.py`：5 passed
  - `python -m pytest server\tests`：60 passed
  - `npm run build`：passed

## 完成任务进度

100%
