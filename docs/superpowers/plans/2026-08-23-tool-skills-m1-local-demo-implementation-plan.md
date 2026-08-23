# Tool Skills M1 Local Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 交付一个仅限本地开发/测试使用、可由管理员创建发布并由 Chat 用户手动执行的 Tool Skill 最小闭环。

**Architecture:** M1 使用固定的 LocalDemoIdentityMiddleware、单一 local-demo namespace 和代码内置的 customer_report_search Handler。Skill 只保存 Tool Skill 元数据、受限输入 Schema、草稿/发布指针和执行结果；客户端请求只能携带 skillId 与结构化 input，不得携带版本、Connector、Operation、角色、URL、SQL 或凭据。M1 不连接真实外部系统，也不声明提供真实登录、租户隔离或 RBAC 安全能力。

**Tech Stack:** FastAPI、Pydantic、SQLAlchemy、Alembic、SQLite/PostgreSQL、React 19、TypeScript、Vite、TanStack Query、既有 Chat SSE、pytest、Vitest、Playwright。

---

## 0. 文档定位、前置条件和边界

本文件是 M1 的独立实施计划。总览和跨里程碑任务映射保留在：

D:\codeproject\python\lingxi\docs\superpowers\plans\2026-08-23-tool-skills-implementation-plan.md

M1 从现有代码基线创建分支 codex/tool-skills-m1，完成后建立标签 tool-skills-m1-local-demo。M1 完成后，开发者无需实现 M2/M3 功能即可启动服务、打开后台、创建 Skill、发布 Skill、进入 Chat 并执行 Skill。

M1 明确不实现：

- 真实登录、会话续期、租户上下文和租户隔离；
- SKILL_READ、SKILL_EXECUTE、SKILL_MANAGE 或其他生产权限校验；
- Connector/Operation 注册、绑定、连接配置和外部网络访问；
- 版本历史、差异、回滚、归档、长任务、超时、取消、产物下载；
- 收藏、默认参数保存、显示名称、排序和 SkillPreset；
- Agent Skills ZIP 导入/导出；
- Chat 用户创建、发布或共享真正的 Skill。用户只能使用管理员发布的系统 Tool Skill。

M1 的安全边界是不可对外暴露的本地演示模式：

- 必须显式设置 SKILLS_M1_LOCAL_DEMO_MODE=true；
- 只接受 loopback 请求；
- 只识别 system_admin 和 demo_employee 两个本地演示身份；
- 关闭开关、非 loopback、伪造控制字段或普通 Chat 自动触发时，服务端必须拒绝；
- 固定 Handler 不读取网络、文件、数据库、环境凭据或用户传入的代码。

## 1. M1 完成后的独立人工闭环

启动服务后，人工应能完成：

1. 以 system_admin 进入后台 Skills 页面。
2. 创建“客户数据”分类。
3. 创建 customer-report-search Tool Skill，填写名称、描述和参数 Schema。
4. 输入非法字段时看到阻断错误，修正后保存草稿。
5. 点击发布，状态变为“已发布”。
6. 切换 demo_employee，进入 Chat 的 Skills 面板。
7. 按分类找到 Skill，填写 query 和 limit。
8. 点击“执行”并再次确认，看到开始、结果、完成事件和 request ID。
9. 发送普通自然语言消息，确认不会自动调用 Skill。
10. 关闭 local-demo 开关或从非 loopback 请求，确认后台和执行接口均被拒绝。

每个 Task 都有独立人工验收步骤；未通过人工验收不得进入下一个 Task。

**Task 独立交付门禁：** 每个 M1 Task 完成后，必须同时满足以下条件，才算完成并允许人工操作下一个 Task：

- 该 Task 交付一个可独立调用的 API、迁移/CLI 能力或页面功能，不以“后续 Task 补齐”作为完成理由；
- 该 Task 的 focused 自动化测试、迁移检查、类型检查或构建门禁全部通过；
- 按本 Task 的“人工验收”步骤在本地真实服务上操作一次，不能只依赖 mock 或单元测试；
- 保存请求/响应、页面截图、日志或数据库检查结果等验收证据，并在提交信息中标明 `M1-xx`。

## 2. M1 任务总表

| Task | 独立功能 | 完成后人工操作 | 自动化门禁 |
|---|---|---|---|
| M1-01 | Tool Skill 合同和本地模式开关 | Swagger/命令行确认模式状态、非法请求被拒绝 | contract、local-demo tests |
| M1-02 | 分类和 Skill 数据持久化 | 迁移后查看分类、草稿和执行表 | model、migration tests |
| M1-03 | 分类管理和 Skill 草稿 API | Swagger 创建分类、编辑草稿、校验和发布 | skills API tests |
| M1-04 | 管理后台列表、分类页和编辑器 | 浏览器创建、保存、校验、发布 Skill | admin Playwright m1 |
| M1-05 | 固定 Demo Handler 和执行 API/SSE | 手动执行并查看安全结果和事件 | execution、SSE tests |
| M1-06 | Chat Skills 面板和手动执行 | 浏览器分类浏览、选择、填写、确认执行 | Chat Playwright m1 |
| M1-07 | M1 安全负向和发布验收 | 关闭开关、非 loopback、字段注入均失败 | M1 e2e/security |

## 3. 文件结构和接口约定

### 后端

- server/app/core/config.py：feature flags、local-demo 开关和 inline driver。
- server/app/middleware/local_demo_identity.py：loopback 和演示身份解析。
- server/app/schemas/skill.py：manifest、输入 Schema、展示配置、草稿和可用定义。
- server/app/schemas/skill_execution.py：SkillRunCreateRequest、执行状态和 SSE 事件。
- server/app/models/skill.py：SkillCategory、Skill、SkillVersion 最小字段。
- server/app/models/skill_execution.py：SkillExecution 和最小执行事件。
- server/app/repositories/skill_repo.py：local-demo namespace 下的分类、草稿、发布版本查询。
- server/app/services/skill_schema_service.py：受限 JSON Schema 和展示配置校验。
- server/app/services/skill_service.py：分类、草稿、校验、发布和 available 查询。
- server/app/services/skill_execution_service.py：统一执行入口和固定 Demo driver。
- server/app/integrations/skills/demo_handler.py：固定 customer_report_search Handler。
- server/app/api/v1/skill_categories.py：分类 CRUD。
- server/app/api/v1/skills.py：Skill 草稿、校验、发布和 available API。
- server/app/api/v1/chat.py：Chat Skill 执行入口和 SSE/查询结果。
- server/app/db/migrations/versions/0009_tool_skills.py：Skill、执行记录和事件表。

### 前端

- web/admin/src/routes/index.tsx：Skills 管理路由和 local-demo 门禁。
- web/admin/src/features/skills/pages/SkillsPage.tsx：Skills 列表。
- web/admin/src/features/skills/pages/SkillCategoriesPage.tsx：分类管理。
- web/admin/src/features/skills/pages/SkillEditorPage.tsx：基本信息、Schema、校验/发布三步编辑器。
- web/admin/src/features/skills/api/skillsApi.ts：分类、草稿、校验、发布 API。
- web/admin/src/features/skills/components/SchemaFieldRow.tsx：参数字段编辑。
- web/admin/src/features/skills/components/ValidationSummary.tsx：阻断错误和警告。
- web/admin/src/features/chat/api/skillApi.ts：分类、available 和 Skill run API。
- web/admin/src/features/chat/components/SkillsDrawer.tsx：分类浏览和手动选择。
- web/admin/src/features/chat/components/SkillDetailPanel.tsx：详情、结构化表单和确认执行。
- web/admin/src/features/chat/components/SkillRunCard.tsx：结果、错误码和 request ID。
- web/admin/tests/t20_tool_skill_admin_playwright.py：M1 管理员验收。
- web/admin/tests/t21_tool_skill_chat_playwright.py：M1 Chat 验收。

M1 Chat 执行 body 固定为 { skillId, input }。允许 Idempotency-Key 作为 header 预留，但 M1 不实现长任务幂等。客户端不得传 skillVersionId、connectorKey、operationKey、roleIds、完整 URL、SQL 或凭据。

## 4. 详细任务

### Task M1-01：冻结合同并建立 Local Demo Gate

**Files:**

- Create: server/app/middleware/local_demo_identity.py
- Create: server/app/schemas/skill.py
- Create: server/app/schemas/skill_execution.py
- Create: server/tests/test_skill_contracts.py
- Create: server/tests/test_local_demo_gate.py
- Modify: server/app/core/config.py
- Modify: server/app/main.py

- [ ] Step 1：先写失败测试。覆盖 skillType 只能是 TOOL、Skill key 的小写连字符规则、描述长度、Schema 根节点 object、additionalProperties=false、禁止 password/credential/url/headers/sql 字段，以及 SkillRunCreateRequest 的 extra=forbid。
- [ ] Step 2：运行失败测试。

~~~powershell
pytest server/tests/test_skill_contracts.py server/tests/test_local_demo_gate.py -q
~~~

预期因 schema、middleware 和配置尚未存在而失败。

- [ ] Step 3：实现合同和开关。增加 SKILLS_M1_CORE_ENABLED、SKILLS_M1_LOCAL_DEMO_MODE、SKILLS_M2_OPERATIONS_ENABLED、SKILLS_M3_IMPORTS_ENABLED、SKILLS_EXECUTION_DRIVER 配置；middleware 必须校验 client host 为 loopback，并解析 system_admin/demo_employee。
- [ ] Step 4：提供 GET /api/v1/skills/runtime，返回当前模式、开关和 execution driver，不返回密钥或内部路径；用 Swagger/curl 人工检查。
- [ ] Step 5：测试通过后提交。

~~~powershell
git add server/app/middleware/local_demo_identity.py server/app/schemas server/app/core/config.py server/app/main.py server/tests/test_skill_contracts.py server/tests/test_local_demo_gate.py
git commit -m "feat: add tool skill contract and local demo gate"
~~~

**人工验收：** Swagger 显示 local-demo；关闭开关返回 FEATURE_DISABLED；非 loopback 返回 LOCAL_DEMO_ONLY；请求注入 operationKey、url、sql、credential 返回 4xx。

### Task M1-02：建立最小持久化和迁移

**Files:**

- Create: server/app/models/skill.py
- Create: server/app/models/skill_execution.py
- Create: server/app/db/migrations/versions/0009_tool_skills.py
- Modify: server/app/db/base.py
- Create: server/tests/test_skill_models.py
- Create: server/tests/test_skill_migrations.py

- [ ] Step 1：写失败模型测试。验证 SkillCategory key 唯一、Skill key 在 namespace_id 内唯一、SkillVersion 版本号唯一；执行记录保存 request ID、脱敏 input/result 和事件序列。
- [ ] Step 2：运行失败测试。

~~~powershell
pytest server/tests/test_skill_models.py server/tests/test_skill_migrations.py -m m1 -q
~~~

- [ ] Step 3：实现模型：SkillCategory(namespace_id,key,name,description,is_active)、Skill(namespace_id,key,name,description,skill_type,category_id,status,current_draft_id,published_version_id)、SkillVersion(skill_id,version_number,manifest,input_schema,presentation_config,execution_policy,demo_handler_key,status,content_hash,created_by_user_id,published_at)、SkillExecution 和 SkillExecutionEvent。
- [ ] Step 4：M1 固定 namespace_id=local-demo；为 M2/M3 预留 tenant、role grant、Connector、artifact、preset、import 字段可以接受，但不暴露对应 API/UI。
- [ ] Step 5：运行迁移和测试。

~~~powershell
alembic upgrade head
pytest server/tests/test_skill_models.py server/tests/test_skill_migrations.py -m m1 -q
alembic downgrade -1
alembic upgrade head
~~~

- [ ] Step 6：提交。

~~~powershell
git add server/app/models/skill.py server/app/models/skill_execution.py server/app/db/base.py server/app/db/migrations/versions/0009_tool_skills.py server/tests/test_skill_models.py server/tests/test_skill_migrations.py
git commit -m "feat: persist local tool skills and executions"
~~~

**人工验收：** 迁移后在数据库中看到 Skill、Version、Execution、Event 表；重复 key 被拒绝；downgrade/upgrade 后索引仍在。

### Task M1-03：实现分类管理和 Skill 草稿/校验/发布 API

**Files:**

- Create: server/app/repositories/skill_repo.py
- Create: server/app/services/skill_schema_service.py
- Create: server/app/services/skill_service.py
- Create: server/app/api/v1/skill_categories.py
- Create: server/app/api/v1/skills.py
- Modify: server/app/api/v1/__init__.py
- Create: server/tests/test_skills_api.py

- [ ] Step 1：写 M1 API 失败测试。Demo admin 可以创建分类和 Skill；无效 Schema 返回 SKILL_SCHEMA_INVALID；发布前必须有 active category；员工不能创建/发布；客户端提交 handler、operation 或 role 字段必须被拒绝。
- [ ] Step 2：运行失败测试。

~~~powershell
pytest server/tests/test_skills_api.py -m m1 -q
~~~

- [ ] Step 3：实现路由：GET/POST/PATCH /api/v1/skill-categories、GET/POST/PATCH /api/v1/skills、GET /api/v1/skills/{skill_id}、POST /api/v1/skills/{skill_id}/validate、POST /api/v1/skills/{skill_id}/publish、GET /api/v1/skills/available。
- [ ] Step 4：发布服务端强制写入 demo_handler_key=customer_report_search；已发布内容只能回写编辑草稿，不能原地修改；M1 不提供版本历史、角色授权或 Operation 绑定。
- [ ] Step 5：用 Swagger 完成分类创建、Skill 创建、非法 Schema、修正、validate、publish 和 available 查询。
- [ ] Step 6：测试通过后提交。

~~~powershell
git add server/app/repositories/skill_repo.py server/app/services/skill_schema_service.py server/app/services/skill_service.py server/app/api/v1/skill_categories.py server/app/api/v1/skills.py server/app/api/v1/__init__.py server/tests/test_skills_api.py
git commit -m "feat: add local tool skill management APIs"
~~~

**人工验收：** 使用 Swagger 完成“分类创建 → Skill 创建 → Schema 校验失败 → 修正 → 发布 → available 查询”；响应带 request ID，Skill 类型只能是 TOOL。

### Task M1-04：实现后台 Skills 列表、分类管理和 Tool Skill 编辑器

**Files:**

- Modify: web/admin/src/routes/index.tsx
- Create: web/admin/src/features/skills/pages/SkillsPage.tsx
- Create: web/admin/src/features/skills/pages/SkillCategoriesPage.tsx
- Create: web/admin/src/features/skills/pages/SkillEditorPage.tsx
- Create: web/admin/src/features/skills/components/SchemaFieldRow.tsx
- Create: web/admin/src/features/skills/components/ValidationSummary.tsx
- Create: web/admin/src/features/skills/components/ConfirmActionDialog.tsx
- Create: web/admin/src/features/skills/api/skillsApi.ts
- Create: web/admin/src/features/skills/utils/skillFormValidation.ts
- Create: web/admin/tests/skills/skillFormValidation.test.ts
- Modify: web/admin/tests/t20_tool_skill_admin_playwright.py

- [ ] Step 1：写前端失败测试。覆盖字段增删改、key 格式、禁止字段、默认值类型、发布前错误阻断，以及 M1 不渲染 Operation/角色/Preset 控件。
- [ ] Step 2：实现 Skills 列表（搜索、分类、状态、更新时间、新建）、分类页（新增、编辑、停用）和三步编辑器（基本信息 → 参数 Schema → 校验/发布）。
- [ ] Step 3：编辑器固定显示 Tool Skill / customer_report_search Demo Handler；不得渲染 Connector、Operation、URL、SQL、凭据、角色、收藏、默认参数、显示名称和排序。
- [ ] Step 4：运行前端和浏览器测试。

~~~powershell
cd web/admin
npm test -- --run src/features/skills
npm run typecheck
npm run lint
npm run build
cd ../..
pytest web/admin/tests/t20_tool_skill_admin_playwright.py -m m1 -q
~~~

- [ ] Step 5：提交。

~~~powershell
git add web/admin/src/routes/index.tsx web/admin/src/features/skills web/admin/tests/skills web/admin/tests/t20_tool_skill_admin_playwright.py
git commit -m "feat: add m1 tool skill admin workflow"
~~~

**人工验收：** 浏览器以 system_admin 完成分类、Skill 创建、非法 Schema 阻断、合法 Schema 保存、校验和发布；刷新后状态仍为已发布；编辑器没有 Connector/Operation/角色/Preset 控件。

### Task M1-05：实现固定 Demo Handler、Inline Driver 和 Chat Skill API

**Files:**

- Create: server/app/integrations/skills/demo_handler.py
- Create: server/app/services/skill_execution_service.py
- Create: server/app/services/skill_sse_service.py
- Modify: server/app/api/v1/chat.py
- Modify: server/app/models/chat.py
- Create: server/tests/test_skill_execution.py
- Create: server/tests/test_skill_sse.py
- Create: server/tests/test_skill_chat_api.py

- [ ] Step 1：写失败执行测试。固定 Handler 只接受 query:string 和上限内的 limit:integer；返回本地确定性数据；覆盖输入校验、结果脱敏、大小限制、事件顺序和 Handler 调用计数。
- [ ] Step 2：实现执行服务：local-demo gate → 查询已发布版本 → 校验 input → 创建 execution → started → 调用固定 Handler → 脱敏 result → done/result。Handler 不访问网络、SQL、文件或凭据。
- [ ] Step 3：实现 GET /api/v1/chat/skill-categories、GET /api/v1/chat/skills/available、POST /api/v1/chat/sessions/{session_id}/skill-runs、GET /api/v1/skill-executions/{execution_id}。
- [ ] Step 4：POST body 严格为 { skillId, input }；拒绝 skillVersionId、connectorKey、operationKey、roleIds、url、sql、credential。
- [ ] Step 5：运行测试并提交。

~~~powershell
pytest server/tests/test_skill_execution.py -m m1 -q
pytest server/tests/test_skill_sse.py -m m1 -q
pytest server/tests/test_skill_chat_api.py -m m1 -q
git add server/app/integrations/skills/demo_handler.py server/app/services/skill_execution_service.py server/app/services/skill_sse_service.py server/app/api/v1/chat.py server/app/models/chat.py server/tests/test_skill_execution.py server/tests/test_skill_sse.py server/tests/test_skill_chat_api.py
git commit -m "feat: execute tool skills with inline demo driver"
~~~

**人工验收：** 在 Swagger 中发布 Skill，再 POST Skill run；确认收到 skill_run_started、skill_run_status、skill_run_result、skill_run_done；注入 operationKey、url 或 sql 时返回 4xx 且 Handler 调用数不增加。

### Task M1-06：实现 Chat Skills 抽屉、结构化表单和结果卡

**Files:**

- Create: web/admin/src/features/chat/api/skillApi.ts
- Create: web/admin/src/features/chat/components/SkillsDrawer.tsx
- Create: web/admin/src/features/chat/components/SkillDetailPanel.tsx
- Create: web/admin/src/features/chat/components/SkillRunCard.tsx
- Modify: web/admin/src/features/chat/pages/ChatPage.tsx
- Modify: web/admin/src/features/chat/api/chatApi.ts
- Modify: web/admin/src/features/chat/types.ts
- Create: web/admin/src/features/chat/utils/skillForm.ts
- Create: web/admin/tests/chat/skillForm.test.ts
- Modify: web/admin/tests/t21_tool_skill_chat_playwright.py

- [ ] Step 1：写失败 UI 测试。按分类过滤、手动选择、Schema 表单、必填校验、二次确认、SSE 事件渲染和普通 Chat 文本不触发 Skill。
- [ ] Step 2：实现 Skills 抽屉和详情。只显示 /chat/skills/available 返回的已发布 Skill；表单由服务端 Schema 驱动，Schema default 只在当前表单会话展示，不保存服务端。
- [ ] Step 3：点击“执行”先显示输入摘要和“确认执行”，只有第二次确认才调用 streamSkillRun；普通自然语言 composer 与 Skill 表单分离。
- [ ] Step 4：结果卡显示运行状态、结构化结果、失败码、request ID；M1 不显示取消、进度、产物下载、收藏、显示名称、默认参数和排序。
- [ ] Step 5：运行测试并提交。

~~~powershell
cd web/admin
npm test -- --run src/features/chat
npm run typecheck
npm run lint
npm run build
cd ../..
pytest web/admin/tests/t21_tool_skill_chat_playwright.py -m m1 -q
git add web/admin/src/features/chat web/admin/tests/chat web/admin/tests/t21_tool_skill_chat_playwright.py
git commit -m "feat: add manual tool skill execution in chat"
~~~

**人工验收：** 切换 demo_employee，打开 Chat → Skills，按分类选择 Skill，填写 query/limit，点击执行并二次确认；发送自然语言查询时不产生 Skill run。

### Task M1-07：完成 M1 端到端、安全负向和发布验收

**Files:**

- Create: server/tests/e2e/test_m1_tool_skill_closed_loop.py
- Modify: server/tests/security/test_skill_security.py
- Modify: web/admin/tests/t20_tool_skill_admin_playwright.py
- Modify: web/admin/tests/t21_tool_skill_chat_playwright.py
- Create: docs/development/v1.1/skills/tool-skill-m1-local-demo-runbook.md

- [ ] Step 1：写 M1 e2e，按管理员建分类/Skill → Schema 校验 → 发布 → Demo Chat available → 手动执行 → 事件顺序 → 安全结果验证。
- [ ] Step 2：写安全负向，覆盖非 loopback、开关关闭、管理 API 越权、伪造 skillVersionId/connectorKey/operationKey/roleIds/url/sql/credential。
- [ ] Step 3：写运行手册，记录启动环境变量、身份切换、浏览器步骤、错误码和关闭服务命令；明确 M1 不能部署到 staging/production。
- [ ] Step 4：运行完整 M1 gate。

~~~powershell
$env:SKILLS_M1_CORE_ENABLED = "true"
$env:SKILLS_M1_LOCAL_DEMO_MODE = "true"
$env:SKILLS_M2_OPERATIONS_ENABLED = "false"
$env:SKILLS_M3_IMPORTS_ENABLED = "false"
$env:SKILLS_EXECUTION_DRIVER = "inline-demo"

pytest server/tests/test_skill_contracts.py server/tests/test_local_demo_gate.py -q
pytest server/tests/test_skill_models.py -m m1 -q
pytest server/tests/test_skills_api.py -m m1 -q
pytest server/tests/test_skill_execution.py server/tests/test_skill_sse.py server/tests/test_skill_chat_api.py -m m1 -q
pytest server/tests/security/test_skill_security.py -m m1 -q
pytest server/tests/e2e/test_m1_tool_skill_closed_loop.py -q

cd web/admin
npm test -- --run src/features/skills src/features/chat
npm run typecheck
npm run lint
npm run build
cd ../..
pytest web/admin/tests/t20_tool_skill_admin_playwright.py -m m1 -q
pytest web/admin/tests/t21_tool_skill_chat_playwright.py -m m1 -q
git diff --check
~~~

- [ ] Step 5：实际执行浏览器手工演示并归档截图、日志、测试结果后提交并打标签。

~~~powershell
git add server/tests/e2e/test_m1_tool_skill_closed_loop.py server/tests/security/test_skill_security.py web/admin/tests/t20_tool_skill_admin_playwright.py web/admin/tests/t21_tool_skill_chat_playwright.py docs/development/v1.1/skills/tool-skill-m1-local-demo-runbook.md
git commit -m "test: verify m1 tool skill local demo loop"
git tag tool-skills-m1-local-demo
~~~

**人工验收：** 完整执行本文件第 1 节的 10 步闭环，并保存每一步证据。

## 5. M1 退出条件

- [ ] 后台可以创建分类、创建/编辑 Tool Skill、保存草稿、服务端校验并发布。
- [ ] Chat 可以按分类浏览、手动选择、填写结构化参数、明确确认并执行固定 Demo Handler。
- [ ] 后端 focused suite、M1 e2e、前端测试/类型检查/构建、两个 Playwright marker 和迁移 upgrade/downgrade 全部通过。
- [ ] 非 loopback、关闭开关、伪造控制字段、普通 Chat 自动触发均被拒绝。
- [ ] 页面和 API 不显示 Connector、Operation、角色、登录、租户、Preset、取消、产物下载等 M2/M3 能力。
- [ ] 已完成人工演示记录；M1 仅限本地开发/测试，不能部署到 staging/production。

**M1 可演示结果：** system_admin 创建并发布 customer-report-search，demo_employee 在 Chat 中按分类手动选择并执行，获得结构化安全结果；M1 是一个完整但明确不具备生产认证能力的本地闭环。
