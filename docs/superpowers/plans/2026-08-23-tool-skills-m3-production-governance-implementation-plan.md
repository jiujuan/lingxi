# Tool Skills M3 Personalization and Production Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 在 M2 安全运营闭环上，补齐用户私有 Skill 个性化、Agent Skills 安全导入/导出、Connector 多 Operation 运营和生产级运行治理，同时保持既有租户、角色、审计和 fail-closed 边界。

**Architecture:** M3 的个性化使用租户内、用户级私有 SkillPreset，只保存收藏、显示名称、默认输入和排序，不能改变 Skill、版本、Operation、角色、URL、SQL、凭据或执行策略。Agent Skills ZIP 只能经过解压前安全预检并生成未发布草稿；Connector 和 Operation 仍由服务端 registry 控制。运行治理在 M2 execution snapshot 上增加重试、限流、并发、熔断、结果脱敏和运营指标，不重写 Chat 调用协议。

**Tech Stack:** FastAPI、SQLAlchemy、Alembic、Celery、Redis、PostgreSQL、PyYAML、jsonschema、React 19、TypeScript、TanStack Query、SSE、pytest、Vitest、Playwright。

---

## 0. 文档定位、前置条件和安全边界

本文件从标签 tool-skills-m2-secure-operations 开始实施，在分支 codex/tool-skills-m3 上完成，最后建立标签 tool-skills-m3-production-complete。

总览文件：

D:\codeproject\python\lingxi\docs\superpowers\plans\2026-08-23-tool-skills-implementation-plan.md

M3 开始前必须确认 M2 的真实登录、租户隔离、RBAC、Operation 绑定、版本、异步执行、审计和产物下载均已通过，并且已有执行请求仍严格为 { skillId, input }。

M3 的四项用户个性化功能：

- 收藏：isFavorite；
- 默认参数：defaultInput，按照当前发布版本 Schema 校验；
- 显示名称：displayName，只改变当前用户看到的名称；
- 排序：displayOrder，只改变当前用户 Skills 面板顺序。

这些字段只属于 (tenant_id,user_id,skill_id) 私有 SkillPreset，不得创建、发布、共享或复制真正的 Skill，不得改变 Connector、Operation、角色、权限、URL、SQL、凭据、timeout、side-effect 或安全策略，也不得绕过 SKILL_READ/SKILL_EXECUTE。

M3 导入和 Connector 边界：

- SKILL.md frontmatter 只作为候选元数据；metadata.lingxi 不授予角色、权限或敏感 Operation；
- 导入包拒绝路径穿越、符号链接、scripts/、可执行文件、未知二进制、密钥/.env 模式、超大文件和压缩炸弹；系统永不运行包内脚本；
- 所有 Connector/Operation 必须来自服务端 registry，客户端不能注册任意 URL、SQL、headers 或 credentials。

## 1. M3 完成后的独立人工闭环

1. 已授权用户登录 Chat Skills 面板，收藏 customer-report-search，设置显示名称“我的客户查询”，保存 limit=10 默认参数并调整排序。
2. 刷新和重新登录后，只有该用户保留个性化结果；同租户其他用户和管理员看不到该覆盖。
3. 管理员上传合法 customer-report-export Agent Skills ZIP，先看到预检报告，选择分类和受控 Operation 后生成未发布草稿；导入不会自动发布。
4. 上传含脚本、路径穿越、符号链接、密钥或超大压缩比的恶意包，在业务写入前被拒绝并记录脱敏审计。
5. 管理员配置 fake Connector 健康状态；不可用时新执行 fail closed，恢复后可执行。
6. 管理员选择第二个服务端注册 Operation，验证 Operation-specific schema、重试策略、并发限制和结果脱敏。
7. 触发可重试失败、限流和并发超限，Chat 显示安全提示；重试生成新 execution 并链接原 execution。

每个 Task 都有独立人工验收步骤；未通过不得进入下一个 Task。

**Task 独立交付门禁：** 每个 M3 Task 完成后，必须同时满足以下条件，才算完成并允许人工操作下一个 Task：

- 该 Task 在 M2 标签基础上形成一个可独立使用的个性化、导入、Connector 或治理功能，不把关键行为留到 M3-06 才首次可用；
- 该 Task 的 focused 自动化测试、隐私/安全测试、前端构建或性能门禁全部通过；
- 按本 Task 的“人工验收”步骤在启用对应 feature flag 的真实服务上操作一次，不能只依赖 mock；
- 保存成功、失败、隔离和回滚/关闭开关等验收证据，并在提交信息中标明 `M3-xx`。

## 2. M3 任务总表

| Task | 独立功能 | 完成后人工操作 | 自动化门禁 |
|---|---|---|---|
| M3-01 | 私有 SkillPreset 后端 | 保存收藏/名称/默认参数/排序并验证用户隔离 | preset/privacy/version tests |
| M3-02 | Chat 个性化 UI | 收藏、改名、默认参数、排序和恢复默认 | Chat unit/Playwright m3 |
| M3-03 | Agent Skills 安全导入/导出 | 合法包生成草稿，恶意包阻断，脱敏导出 | import/security tests |
| M3-04 | Connector、多 Operation、健康检查 | 配置 fake connection、健康检查、选择不同 Operation | connector/health tests |
| M3-05 | 重试、限流、并发、脱敏、监控 | 触发重试/限流/熔断，查看指标和审计 | governance/performance tests |
| M3-06 | UX、运行手册和发布验收 | 完成生产演示、开关回归、备份恢复 | full release suite |

## 3. 文件结构和接口约定

- server/app/repositories/skill_preset_repo.py：tenant/user/skill 私有查询。
- server/app/services/skill_preset_service.py：版本校验、隐私和失效标记。
- server/app/schemas/skill_import.py：manifest、预检、冲突和导出响应。
- server/app/services/skill_import_service.py：ZIP 预检、映射、草稿创建和脱敏导出。
- server/app/api/v1/skill_presets.py：Preset 读写。
- server/app/api/v1/skill_import.py：预检、应用导入、冲突和导出。
- server/app/services/connector_service.py：tenant connection、secret reference、health check。
- server/app/services/skill_governance_service.py：retry、rate-limit、concurrency、circuit-breaker、redaction。
- server/app/api/v1/skill_connectors.py：Connector 配置、Operation 和健康检查。
- web/admin/src/features/chat/components/SkillPresetControls.tsx：收藏、名称、默认参数、排序。
- web/admin/src/features/skills/pages/SkillImportPage.tsx：导入预检、映射、冲突和导出。
- web/admin/src/features/skills/pages/ConnectorManagementPage.tsx：Connector、Operation、health 管理。
- web/admin/src/features/skills/components/SecurityScanReport.tsx：导入安全报告。
- docs/development/v1.1/skills/tool-skill-runbook.md：生产运行、故障、恢复和保留策略。

M3 API 约束：Preset body 只能包含 isFavorite、displayName、defaultInput、displayOrder；每次读写重新解析当前 available definition 并按最新 Schema 校验；导入先返回预检报告，应用后只创建未发布草稿；导出脱敏内部 ID、连接和凭据；M3 不能放宽 M2 的租户、权限和 registry 约束。

## 4. 详细任务

### Task M3-01：实现私有 SkillPreset 后端

**Files:**

- Modify: server/app/models/skill.py
- Create: server/app/repositories/skill_preset_repo.py
- Create: server/app/services/skill_preset_service.py
- Create: server/app/api/v1/skill_presets.py
- Create: server/tests/test_skill_preset.py
- Create: server/tests/test_skill_preset_privacy.py

- [ ] Step 1：写失败模型和隐私测试。唯一键为 tenant_id,user_id,skill_id；查询必须双重过滤；无 SKILL_READ/SKILL_EXECUTE 不能读写；管理员不能代替用户写入；禁止 operationKey、roleIds、URL、SQL、credential。
- [ ] Step 2：实现请求 schema，只允许 isFavorite、displayName、defaultInput、displayOrder；读写前从 published available definition 重新校验权限和 Schema。
- [ ] Step 3：实现 GET/PUT /api/v1/skills/{skill_id}/preset；不提供管理员代写接口；版本不兼容返回 PRESET_REVALIDATION_REQUIRED 或失效状态。
- [ ] Step 4：运行测试和 API 人工验证。

~~~powershell
pytest server/tests/test_skill_preset.py server/tests/test_skill_preset_privacy.py -q
~~~

- [ ] Step 5：提交。

~~~powershell
git add server/app/models/skill.py server/app/repositories/skill_preset_repo.py server/app/services/skill_preset_service.py server/app/api/v1/skill_presets.py server/tests/test_skill_preset.py server/tests/test_skill_preset_privacy.py
git commit -m "feat: add private tool skill presets"
~~~

**人工验收：** 用户 A 保存 favorite/name/default/order 后重新请求仍存在；用户 B、管理员和其他租户均不可见；发布新版本删除 limit 后旧 default 标记失效。

### Task M3-02：实现 Chat 个性化控件和排序体验

**Files:**

- Create: web/admin/src/features/chat/components/SkillPresetControls.tsx
- Modify: web/admin/src/features/chat/components/SkillsDrawer.tsx
- Modify: web/admin/src/features/chat/components/SkillDetailPanel.tsx
- Modify: web/admin/src/features/chat/api/skillApi.ts
- Modify: web/admin/src/features/chat/types.ts
- Create: web/admin/tests/chat/skillPreset.test.ts
- Modify: web/admin/tests/t21_tool_skill_chat_playwright.py

- [ ] Step 1：写失败 UI 测试。M3 开关关闭时控件不渲染；开启后 favorite、display name、默认参数、恢复默认和排序调用正确 API；排序只影响当前用户；非法默认字段不提交。
- [ ] Step 2：实现 favorite toggle、display name 编辑、默认参数保存/恢复和排序；显示名称只作为当前用户 label，系统 key/name 保留。
- [ ] Step 3：每次打开 Skill 重新获取 definition 和 preset；默认参数不兼容时显示失效字段并要求确认，不能静默执行旧值。
- [ ] Step 4：运行测试和浏览器验收。

~~~powershell
cd web/admin
npm test -- --run src/features/chat
npm run typecheck
npm run lint
npm run build
cd ../..
pytest web/admin/tests/t21_tool_skill_chat_playwright.py -m m3 -q
git add web/admin/src/features/chat web/admin/tests/chat/skillPreset.test.ts web/admin/tests/t21_tool_skill_chat_playwright.py
git commit -m "feat: add private tool skill personalization in chat"
~~~

**人工验收：** 用户收藏两个 Skill、设置显示名称、保存 limit=10、调整排序；刷新/重新登录仍保持；另一用户看到系统默认名称/顺序；管理员后台没有用户覆盖。

### Task M3-03：实现 Agent Skills 安全导入/导出

**Files:**

- Create: server/app/schemas/skill_import.py
- Create: server/app/services/skill_import_service.py
- Create: server/app/api/v1/skill_import.py
- Create: server/tests/fixtures/skills/customer-report-export/SKILL.md
- Create: server/tests/fixtures/skills/customer-report-export/references/INPUTS.md
- Create: server/tests/fixtures/skills/malicious/
- Create: server/tests/test_skill_import.py
- Create: server/tests/test_skill_package_security.py
- Create: web/admin/src/features/skills/pages/SkillImportPage.tsx
- Create: web/admin/src/features/skills/components/SecurityScanReport.tsx
- Create: web/admin/tests/skills/skillImport.test.ts
- Modify: web/admin/tests/t20_tool_skill_admin_playwright.py

- [ ] Step 1：写失败安全测试。合法包能读取 SKILL.md/references；拒绝 scripts、路径穿越、符号链接、.env/private key、未知二进制、超大成员和压缩炸弹；拒绝前不能提取、执行或写业务 Skill。
- [ ] Step 2：实现预检器。先检查 ZIP central directory、压缩/解压大小、路径归一化、文件类型、manifest、密钥模式和允许目录；只把安全文本放入隔离临时目录；永不加载/运行 scripts。
- [ ] Step 3：实现 POST /api/v1/skill-imports/preflight 和 POST /api/v1/skill-imports/apply；apply 需要管理员选择分类和 registry Operation 映射，只创建未发布草稿；冲突支持新建 Skill/新建草稿版本/取消。
- [ ] Step 4：实现 GET /api/v1/skills/{skill_id}/export，只导出允许的 manifest/reference，去掉内部 ID、secret reference、内部 URL、审计和执行数据。
- [ ] Step 5：运行测试、UI 验证并提交。

~~~powershell
pytest server/tests/test_skill_import.py server/tests/test_skill_package_security.py -q
cd web/admin
npm test -- --run src/features/skills
npm run typecheck
npm run lint
npm run build
cd ../..
pytest web/admin/tests/t20_tool_skill_admin_playwright.py -m m3 -q
git add server/app/schemas/skill_import.py server/app/services/skill_import_service.py server/app/api/v1/skill_import.py server/tests/fixtures/skills server/tests/test_skill_import.py server/tests/test_skill_package_security.py web/admin/src/features/skills web/admin/tests/t20_tool_skill_admin_playwright.py
git commit -m "feat: add safe agent skill import and export"
~~~

**人工验收：** 上传合法 fixture，看到预检报告并生成未发布草稿；上传脚本、路径穿越、符号链接、.env fixture，在业务写入前阻断；导出不含连接、凭据、内部 ID 或执行数据。

### Task M3-04：实现 Connector 管理、多 Operation 和健康检查

**Files:**

- Modify: server/app/integrations/skills/registry.py
- Create: server/app/integrations/skills/operations/database_readonly.py
- Create: server/app/integrations/skills/operations/internal_http.py
- Create: server/app/integrations/skills/operations/file_processing.py
- Modify: server/app/models/connector.py
- Modify: server/app/services/connector_service.py
- Modify: server/app/api/v1/skill_connectors.py
- Create: server/tests/test_connector_health.py
- Create: web/admin/src/features/skills/pages/ConnectorManagementPage.tsx
- Modify: web/admin/tests/t20_tool_skill_admin_playwright.py

- [ ] Step 1：写失败 registry/health 测试。只能返回 approved operations；tenant connection 只能引用 secret reference；health unavailable 时新 execution 拒绝；恢复后经过 health TTL 才重新启用；客户端 Operation key/URL/SQL/credential 不被接受。
- [ ] Step 2：增加只读数据库模板、registered internal HTTP、file-processing fake Operation；每个 Operation 声明 input/output schema、side-effect、timeout、retry 和 redaction ceiling；不开放自由 SQL/任意 URL。
- [ ] Step 3：实现 tenant connection 和健康检查；只接受非敏感配置和 opaque secret reference；日志不写 secret/endpoint；dispatch 前检查健康状态。
- [ ] Step 4：实现 Connector 列表、Operation 目录、连接状态、健康检查和 safe error UI。
- [ ] Step 5：运行测试和人工操作并提交。

~~~powershell
pytest server/tests/test_connector_health.py server/tests/test_skill_connectors.py server/tests/test_skill_operations.py -q
pytest web/admin/tests/t20_tool_skill_admin_playwright.py -m m3 -q
git add server/app/integrations/skills server/app/models/connector.py server/app/services/connector_service.py server/app/api/v1/skill_connectors.py server/tests/test_connector_health.py web/admin/src/features/skills/pages/ConnectorManagementPage.tsx web/admin/tests/t20_tool_skill_admin_playwright.py
git commit -m "feat: add connector health and controlled operations"
~~~

**人工验收：** 管理员查看多个 Operation，配置 fake connection，健康检查成功/失败可见；不可用阻断新执行，恢复后可执行；页面和日志没有 secret、内部 URL 或自由 SQL。

### Task M3-05：实现重试、限流、并发、脱敏和运营监控

**Files:**

- Create: server/app/services/skill_governance_service.py
- Modify: server/app/services/skill_execution_service.py
- Modify: server/app/tasks/skill_tasks.py
- Modify: server/app/services/skill_audit_service.py
- Modify: web/admin/src/features/chat/components/SkillRunCard.tsx
- Create: web/admin/src/features/skills/pages/SkillOperationsMetricsPage.tsx
- Create: server/tests/test_skill_governance.py
- Create: server/tests/test_skill_redaction.py
- Modify: web/admin/tests/t21_tool_skill_chat_playwright.py

- [ ] Step 1：写失败治理测试。可重试错误按 Operation policy 退避且不超过次数；手动重试产生新 execution 并链接 original；用户/tenant/Skill/Operation 的 rate-limit 和 concurrency 超限返回稳定错误；熔断后不派发；结果脱敏覆盖 secret/token/header/PII。
- [ ] Step 2：实现治理服务。dispatch 依次检查 quota、rate limit、concurrency、health、circuit；worker 只按服务端 policy 重试；retry/circuit/limit 写审计和指标；客户端不能覆盖 retry/timeout/concurrency。
- [ ] Step 3：实现 Chat 安全提示和指标页；展示 count/status/duration/queue latency/timeout/cancel/artifact bytes/import rejection/health，不展示输入和凭据。
- [ ] Step 4：运行治理测试和人工压测。

~~~powershell
pytest server/tests/test_skill_governance.py server/tests/test_skill_redaction.py -q
pytest web/admin/tests/t21_tool_skill_chat_playwright.py -m m3 -q
git add server/app/services/skill_governance_service.py server/app/services/skill_execution_service.py server/app/tasks/skill_tasks.py server/app/services/skill_audit_service.py web/admin/src/features/chat/components/SkillRunCard.tsx web/admin/src/features/skills/pages/SkillOperationsMetricsPage.tsx server/tests/test_skill_governance.py server/tests/test_skill_redaction.py web/admin/tests/t21_tool_skill_chat_playwright.py
git commit -m "feat: add tool skill runtime governance"
~~~

**人工验收：** 触发可重试错误，确认重试次数受限且新 execution 关联原记录；超过 quota 显示限流；连续健康失败后熔断；指标和审计没有 token、URL、SQL 或敏感输入。

### Task M3-06：完成生产 UX、运行手册和全量发布验收

**Files:**

- Modify: web/admin/src/features/skills/pages/SkillsPage.tsx
- Modify: web/admin/src/features/chat/pages/ChatPage.tsx
- Create: docs/development/v1.1/skills/tool-skill-runbook.md
- Create: server/tests/e2e/test_m3_tool_skill_complete.py
- Create: server/tests/security/test_tool_skill_m3_security.py
- Create: server/tests/test_tool_skill_performance.py
- Modify: server/tests/test_skill_release_acceptance.py
- Modify: web/admin/tests/t20_tool_skill_admin_playwright.py
- Modify: web/admin/tests/t21_tool_skill_chat_playwright.py

- [ ] Step 1：补齐桌面/窄屏响应式、键盘导航、确认弹窗、错误码可读性；Connector 不可用时普通 Chat 仍可用。
- [ ] Step 2：runbook 必须包含迁移/seed upgrade、worker、flags、health、secret rotation、import rejection、retry/timeout/cancel、artifact cleanup、audit retention、quota、backup/restore、rollback 和 incident response。
- [ ] Step 3：e2e 和安全测试必须验证 M1/M2 在 M3 flags 下继续通过；关闭 M3 import/preset 不影响已有已发布 Skill；没有脚本执行、任意 URL、自由 SQL、包内凭据、跨租户访问、未授权下载或模型自动调用。
- [ ] Step 4：运行完整验证。

~~~powershell
pytest server/tests/test_skill_contracts.py server/tests/test_skill_models.py server/tests/test_skill_permissions.py server/tests/test_skill_connectors.py server/tests/test_skill_operations.py server/tests/test_skills_api.py server/tests/test_skill_import.py server/tests/test_skill_preset.py server/tests/test_skill_execution.py server/tests/test_skill_sse.py server/tests/test_skill_chat_api.py server/tests/security/test_skill_security.py server/tests/security/test_tool_skill_m3_security.py server/tests/e2e/test_m3_tool_skill_complete.py server/tests/test_tool_skill_performance.py -q

cd web/admin
npm test
npm run typecheck
npm run lint
npm run build
cd ../..
pytest web/admin/tests/t20_tool_skill_admin_playwright.py -m "m1 or m2 or m3" -q
pytest web/admin/tests/t21_tool_skill_chat_playwright.py -m "m1 or m2 or m3" -q
git diff --check
~~~

- [ ] Step 5：完成备份恢复、健康失败、限流、导入开关关闭和恢复操作，归档证据后提交并打标签。

~~~powershell
git add web/admin/src/features/skills web/admin/src/features/chat docs/development/v1.1/skills server/tests/e2e/test_m3_tool_skill_complete.py server/tests/security/test_tool_skill_m3_security.py server/tests/test_tool_skill_performance.py server/tests/test_skill_release_acceptance.py web/admin/tests/t20_tool_skill_admin_playwright.py web/admin/tests/t21_tool_skill_chat_playwright.py
git commit -m "test: complete tool skill production acceptance"
git tag tool-skills-m3-production-complete
~~~

**人工验收：** 依次完成 preset 隔离、合法/恶意包导入、Connector health、重试/限流、备份恢复和功能开关回归；确认关闭 M3 不会降级到未认证执行，M1/M2 已发布 Skill 不丢失。

## 5. M3 退出条件

- [ ] 收藏、默认参数、显示名称、排序和私有 SkillPreset 均有服务端隐私校验、版本失效、前端和浏览器测试。
- [ ] 合法 Agent Skills 包可预检并生成未发布草稿；恶意包在解压/写业务数据前被阻断；导出内容脱敏。
- [ ] Connector、Operation、tenant connection 和 health check 全部由服务端 registry/权限控制。
- [ ] 重试、限流、并发、熔断、结果脱敏和运营指标可人工演示，不能被客户端覆盖策略。
- [ ] M1/M2/M3 自动化、迁移、类型检查、构建、Playwright、性能基线和安全 suite 全部通过。
- [ ] M3 runbook、监控、数据保留、备份恢复和故障演练完成。
- [ ] M3 不引入 Prompt Skill、模型自动选择、自治编排或共享用户 Skill。

**M3 可演示结果：** 用户可以安全地个性化自己有权限使用的 Skill；管理员可以安全导入包并映射到受控 Operation；系统在连接器异常、恶意包、权限变化和资源压力下仍保持可解释、可审计和 fail closed。
