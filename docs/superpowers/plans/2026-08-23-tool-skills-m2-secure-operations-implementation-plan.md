# Tool Skills M2 Secure Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 在 M1 本地 Demo 闭环之上，加入基础登录、租户隔离、SKILL_READ/SKILL_EXECUTE/管理权限校验、服务端预注册 fake Connector Operation、版本生命周期、异步执行、审计和产物下载，使 Tool Skill 成为第一个可进入受控 staging/production 的安全运营闭环。

**Architecture:** M2 从 local-demo 身份切换到既有登录/会话体系，在每个 repository 查询和 service mutation 中强制绑定 tenant_id 与权限上下文。Connector Operation 只能由服务端静态 registry 提供，第一期只开放 knowledge-base.search fake Operation；客户端始终只提交 { skillId, input }。统一 SkillExecutionService 在队列前锁定租户、发布版本、Operation 契约和角色快照，Celery worker 只执行已审核的服务端 Operation。

**Tech Stack:** FastAPI、既有登录和 RBAC、SQLAlchemy、Alembic、Celery、Redis、PostgreSQL、React 19、TypeScript、TanStack Query、SSE、pytest、Vitest、Playwright。

---

## 0. 文档定位、前置条件和边界

本文件从标签 tool-skills-m1-local-demo 开始实施，在分支 codex/tool-skills-m2 上完成，最后建立标签 tool-skills-m2-secure-operations。

总览文件：

D:\codeproject\python\lingxi\docs\superpowers\plans\2026-08-23-tool-skills-implementation-plan.md

M2 开始前必须确认 M1 闭环仍通过，并且现有用户、角色、权限、会话和租户表可用。M2 不允许以 M1 固定演示身份冒充生产认证。

M2 包含：

- 基础登录、会话过期和登录态恢复；
- 当前用户、当前租户和角色快照；
- SKILL_READ、SKILL_EXECUTE、SKILL_MANAGE、SKILL_CATEGORY_MANAGE、SKILL_CONNECTOR_MANAGE、SKILL_AUDIT_READ；
- 租户内 Skill/Category/Version/Execution/Artifact 查询；
- 服务端预注册且客户端不可扩展的 knowledge-base.search fake Connector Operation；
- Skill 与 Operation 绑定、角色授权、版本历史、差异、回滚为新版本、禁用和归档；
- Celery 异步执行、进度、超时、取消、幂等和审计；
- 产物下载和下载越权拒绝。

M2 不包含：收藏、默认参数、显示名称、排序和 SkillPreset；Agent Skills 包导入/导出；用户自定义 Connector、任意 URL、自由 SQL、脚本或凭据；多 Operation 运营、完整重试/限流/并发治理。

## 1. M2 完成后的独立人工闭环

1. 管理员通过真实登录进入租户 A。
2. 从服务端只读 Operation 目录选择 knowledge-base.search，配置策略和角色授权。
3. 校验并发布版本 1；授权用户登录 Chat，只看到同时满足 SKILL_READ、SKILL_EXECUTE、published、enabled 的 Skill。
4. 用户手动执行，看到排队、执行、进度和结果；长任务可以取消，超时有错误码。
5. 管理员发布版本 2，查看差异；旧执行继续指向版本 1；不能原地修改已发布版本。
6. 禁用/归档 Skill 后新的执行被阻断，历史执行和审计仍可查询。
7. 授权用户可以下载产物，跨租户或无权用户下载失败。

每个 Task 都有独立人工验收步骤；未通过不得进入下一个 Task。

**Task 独立交付门禁：** 每个 M2 Task 完成后，必须同时满足以下条件，才算完成并允许人工操作下一个 Task：

- 该 Task 在 M1 标签基础上形成一个可独立使用的安全功能，API、管理 UI 或 Chat UI 至少有一条真实操作路径；
- 该 Task 的 focused 自动化测试、迁移/seed 检查、前端构建或安全测试全部通过；
- 按本 Task 的“人工验收”步骤使用真实登录、租户或受控 fake Operation（按任务范围）操作一次，不能只依赖 mock；
- 保存权限拒绝、状态变化和成功路径的验收证据，并在提交信息中标明 `M2-xx`。

## 2. M2 任务总表

| Task | 独立功能 | 完成后人工操作 | 自动化门禁 |
|---|---|---|---|
| M2-01 | 登录、会话、租户上下文和 Skill RBAC | 不同用户/租户登录并验证权限差异 | auth、RBAC、tenant tests |
| M2-02 | 静态 fake registry 和 Operation 绑定 | 编辑器选择 knowledge-base.search 并检查契约 | connector/operation tests |
| M2-03 | 版本、角色授权、禁用、归档、回滚 | 发布 v1/v2、查看 diff、撤权、归档 | lifecycle/version tests |
| M2-04 | Celery 状态机、超时、取消、幂等、审计、产物 | 观察长任务、取消、超时、下载产物 | execution/audit/artifact tests |
| M2-05 | 管理后台安全运营 UI | 完成绑定、授权、版本、生命周期和审计查询 | admin Playwright m2 |
| M2-06 | Chat 权限过滤、状态卡、取消和下载 | 切换租户/角色验证可见、取消、越权下载 | Chat/security tests |
| M2-07 | M2 端到端发布门禁 | 按 runbook 完成 staging 演示 | M2 e2e/release suite |

## 3. 文件结构和接口约定

- server/app/services/seed_service.py：幂等创建 Skill 权限并升级已有租户角色映射。
- server/app/core/auth_context.py：解析 user/tenant/roles/permissions。
- server/app/integrations/skills/registry.py：静态 Operation registry。
- server/app/integrations/skills/operations/knowledge_base.py：knowledge-base.search fake Operation。
- server/app/services/connector_service.py：Operation 可用性和 safe connection 检查。
- server/app/services/skill_authorization_service.py：租户、权限、角色 grant 和发布状态决策。
- server/app/services/skill_lifecycle_service.py：版本发布、diff、禁用、归档和回滚为新版本。
- server/app/tasks/skill_tasks.py：Celery worker、超时和取消。
- server/app/services/skill_audit_service.py：脱敏审计事件写入和查询。
- server/app/services/artifact_service.py：产物保存、短时下载 token 和权限校验。
- server/app/api/v1/skill_connectors.py：预注册 Operation 目录和绑定 API。
- server/app/api/v1/skill_audit.py：审计查询。
- server/app/api/v1/skill_artifacts.py：产物元数据和下载。
- web/admin/src/features/skills/components/OperationSelector.tsx：只显示 registry Operation。
- web/admin/src/features/skills/components/RoleGrantEditor.tsx：角色授权。
- web/admin/src/features/skills/components/VersionHistoryPanel.tsx：版本、diff 和新版本回滚。
- web/admin/src/features/skills/components/LifecycleActions.tsx：禁用、归档和确认。
- web/admin/src/features/skills/pages/SkillAuditPage.tsx：脱敏审计。
- web/admin/src/features/chat/components/SkillRunCard.tsx：排队、进度、超时、取消、终态和产物。

M2 强约束：管理 mutation 只读取当前 session 的 user/tenant/permission；Chat body 仍是 { skillId, input }；版本/Operation/role 从服务端发布版本解析；Idempotency-Key 只能在 header；错误码包含 AUTH_REQUIRED、TENANT_SCOPE_VIOLATION、SKILL_READ_FORBIDDEN、SKILL_EXECUTE_FORBIDDEN、OPERATION_NOT_AVAILABLE、EXECUTION_TIMEOUT、EXECUTION_CANCELLED；所有拒绝路径 fail closed。

## 4. 详细任务

### Task M2-01：接入基础登录、租户上下文和 Skill RBAC

**Files:**

- Modify: server/app/services/seed_service.py
- Modify: server/app/core/auth_context.py
- Modify: existing login/session middleware and server/app/api/v1/auth.py
- Modify: server/app/repositories/skill_repo.py
- Create: server/app/services/skill_authorization_service.py
- Create: server/tests/test_skill_permissions.py
- Create: server/tests/test_skill_tenant_isolation.py
- Modify: web/admin/src/routes/index.tsx
- Create: web/admin/tests/auth/skillPermissionGuards.test.ts

- [ ] Step 1：写失败权限测试。SYSTEM_ADMIN 获得全部 Skill 权限，KNOWLEDGE_ADMIN/EMPLOYEE 至少获得 SKILL_READ、SKILL_EXECUTE；重复 seed 不产生重复关系；跨租户 Skill ID 返回 404/403；无权限管理请求被拒绝。
- [ ] Step 2：实现 session/tenant context。所有 Skill repository query 强制 tenant_id == context.tenant_id；管理 API 不接受 body/query/header 的 tenantId；会话过期统一返回 AUTH_REQUIRED。
- [ ] Step 3：实现权限矩阵。SKILL_READ 控制列表/详情，SKILL_EXECUTE 控制执行，SKILL_MANAGE 控制草稿/版本，SKILL_CATEGORY_MANAGE 控制分类，SKILL_AUDIT_READ 控制审计；Skill role grant 是额外执行条件。
- [ ] Step 4：运行测试并人工验证。

~~~powershell
pytest server/tests/test_skill_permissions.py server/tests/test_skill_tenant_isolation.py -q
pytest server/tests/test_auth_rbac.py -q
~~~

用 tenant-a/admin、tenant-a/employee、tenant-b/employee 登录浏览器，验证管理页、Chat 列表和 API 的差异。

- [ ] Step 5：提交。

~~~powershell
git add server/app/services/seed_service.py server/app/core/auth_context.py server/app/repositories/skill_repo.py server/app/services/skill_authorization_service.py server/tests/test_skill_permissions.py server/tests/test_skill_tenant_isolation.py web/admin/src/routes/index.tsx web/admin/tests/auth/skillPermissionGuards.test.ts
git commit -m "feat: enforce tool skill auth and tenant scope"
~~~

**人工验收：** tenant-a 管理员可以管理；employee 不能创建/发布；tenant-a 看不到 tenant-b；撤销 SKILL_READ 后列表消失，撤销 SKILL_EXECUTE 后只能查看不能执行；过期 session 回到登录页。

### Task M2-02：注册 fake Connector Operation 并支持服务端绑定

**Files:**

- Create: server/app/integrations/skills/protocols.py
- Create: server/app/integrations/skills/registry.py
- Create: server/app/integrations/skills/operations/knowledge_base.py
- Create: server/app/api/v1/skill_connectors.py
- Modify: server/app/models/connector.py
- Modify: server/app/services/connector_service.py
- Create: server/tests/test_skill_connectors.py
- Create: server/tests/test_skill_operations.py
- Modify: web/admin/src/features/skills/pages/SkillEditorPage.tsx
- Create: web/admin/src/features/skills/components/OperationSelector.tsx
- Create: web/admin/tests/skills/operationSelector.test.ts

- [ ] Step 1：写失败 registry 安全测试。M2 可用集合只有 knowledge-base.search；未知 key、完整 URL、SQL、凭据、自定义 handler 均被拒绝；timeout/input/output/side-effect ceiling 可验证。
- [ ] Step 2：实现静态 registry。客户端不能新增、覆盖或删除；fake Operation 使用本地数据集，支持可控延迟、成功、超时和可重试失败，但不访问真实知识库。
- [ ] Step 3：实现绑定和发布前校验。草稿保存 connector_operation_id；发布时重新解析 registry contract；策略不能超过 Operation ceiling；不可用或 key 失效时 fail closed。
- [ ] Step 4：提供 GET /api/v1/skill-connectors/operations，只返回 key、显示名、schema、side-effect 和限制，不返回内部 URL、密钥或实现路径。
- [ ] Step 5：运行测试并人工操作。

~~~powershell
pytest server/tests/test_skill_connectors.py server/tests/test_skill_operations.py -q
pytest web/admin/tests/skills/operationSelector.test.ts -q
~~~

- [ ] Step 6：提交。

~~~powershell
git add server/app/integrations/skills server/app/api/v1/skill_connectors.py server/app/models/connector.py server/app/services/connector_service.py server/tests/test_skill_connectors.py server/tests/test_skill_operations.py web/admin/src/features/skills web/admin/tests/skills/operationSelector.test.ts
git commit -m "feat: bind tool skills to registered fake operations"
~~~

**人工验收：** 管理员在编辑器选择 knowledge-base.search；DevTools 把 request 改为 evil-operation、外部 URL 或 SQL 时返回 OPERATION_NOT_ALLOWED，草稿不被污染。

### Task M2-03：实现版本、角色授权、禁用、归档和回滚

**Files:**

- Modify: server/app/models/skill.py
- Create: server/app/services/skill_lifecycle_service.py
- Modify: server/app/api/v1/skills.py
- Create: server/tests/test_skill_versions.py
- Create: server/tests/test_skill_lifecycle.py
- Modify: web/admin/src/features/skills/pages/SkillEditorPage.tsx
- Create: web/admin/src/features/skills/components/VersionHistoryPanel.tsx
- Create: web/admin/src/features/skills/components/RoleGrantEditor.tsx
- Create: web/admin/src/features/skills/components/LifecycleActions.tsx
- Modify: web/admin/tests/t20_tool_skill_admin_playwright.py

- [ ] Step 1：写失败测试。已发布版本不可原地更新；发布新版本产生单调递增 version number；diff 脱敏；回滚复制为新版本；没有当前租户 role grant 不能发布/执行；禁用/归档阻止新执行但不删除历史。
- [ ] Step 2：提供 POST /api/v1/skills/{skill_id}/versions、GET versions、GET versions/{version_id}/diff、POST versions/{version_id}/publish、PUT versions/{version_id}/role-grants、POST disable、POST archive、POST rollback。
- [ ] Step 3：同一事务锁定发布指针、Operation、role grant 和策略 ceiling；审计接入后，审计写入失败不能发布成功。
- [ ] Step 4：运行测试并人工操作：发布 v1，修改并发布 v2，查看 diff，回滚成 v3，撤销执行角色，归档后验证新 run 被拒绝。
- [ ] Step 5：提交。

~~~powershell
git add server/app/models/skill.py server/app/services/skill_lifecycle_service.py server/app/api/v1/skills.py server/tests/test_skill_versions.py server/tests/test_skill_lifecycle.py web/admin/src/features/skills web/admin/tests/t20_tool_skill_admin_playwright.py
git commit -m "feat: add tool skill version and lifecycle controls"
~~~

**人工验收：** 浏览器完成 v1 → v2 → diff → rollback as v3；旧版本未被篡改；禁用/归档有确认弹窗，Chat 新执行被拒绝，历史记录仍可查看。

### Task M2-04：实现 Celery 状态机、超时、取消、幂等、审计和产物

**Files:**

- Create: server/app/tasks/skill_tasks.py
- Modify: server/app/services/skill_execution_service.py
- Create: server/app/services/skill_audit_service.py
- Create: server/app/services/artifact_service.py
- Create: server/app/api/v1/skill_artifacts.py
- Modify: server/app/models/skill_execution.py
- Modify: server/app/tasks/celery_app.py
- Create: server/tests/test_skill_execution_m2.py
- Create: server/tests/test_skill_audit.py
- Create: server/tests/test_skill_artifacts.py

- [ ] Step 1：写失败状态机测试。覆盖 QUEUED → RUNNING → SUCCEEDED/FAILED/TIMED_OUT/CANCELLED；重复 request ID 只创建一个 execution；cancel/timeout race 只有一个终态；队列、Operation、审计或 artifact 失败必须 fail closed。
- [ ] Step 2：实现 worker。入队保存 tenant、published version、Operation contract、role snapshot、request ID 和脱敏 input；worker 不接受客户端控制字段；按 Operation timeout ceiling；取消使用 cooperative token。
- [ ] Step 3：实现脱敏审计。记录 management、publish、grant、run、cancel、timeout、artifact-download、deny；不得写 token、凭据、完整 URL、SQL 或敏感 input/result。
- [ ] Step 4：实现 artifact。保存 safe filename、MIME、大小、checksum、expiry、classification；下载 token 短时有效，每次重新检查 user/tenant/permission/ownership。
- [ ] Step 5：运行 worker 手动验证，观察 queued/running/progress，取消或等待 timeout，再下载 artifact。

~~~powershell
pytest server/tests/test_skill_execution_m2.py server/tests/test_skill_audit.py server/tests/test_skill_artifacts.py -q
git add server/app/tasks/skill_tasks.py server/app/services/skill_execution_service.py server/app/services/skill_audit_service.py server/app/services/artifact_service.py server/app/api/v1/skill_artifacts.py server/app/models/skill_execution.py server/app/tasks/celery_app.py server/tests/test_skill_execution_m2.py server/tests/test_skill_audit.py server/tests/test_skill_artifacts.py
git commit -m "feat: add secure async tool skill execution"
~~~

**人工验收：** 延迟 run 依次进入 queued/running；取消为 cancelled；超过 ceiling 为 timed out；同一 Idempotency-Key 返回同一 execution；授权用户能下载，跨租户/撤权后失败；审计没有敏感值。

### Task M2-05：完成管理员安全运营 UI

**Files:**

- Modify: web/admin/src/features/skills/pages/SkillsPage.tsx
- Modify: web/admin/src/features/skills/pages/SkillEditorPage.tsx
- Create: web/admin/src/features/skills/pages/SkillAuditPage.tsx
- Modify: web/admin/src/features/skills/components/VersionHistoryPanel.tsx
- Modify: web/admin/src/features/skills/components/OperationSelector.tsx
- Modify: web/admin/src/features/skills/components/RoleGrantEditor.tsx
- Create: web/admin/src/features/skills/components/LifecycleActions.tsx
- Modify: web/admin/tests/t20_tool_skill_admin_playwright.py

- [ ] Step 1：写页面测试。验证租户上下文、权限门禁、Operation 只读目录、role grant、版本 diff、禁用/归档确认和审计脱敏。
- [ ] Step 2：实现登录态和租户栏；session 过期跳转登录；前端隐藏不能代替服务端检查。
- [ ] Step 3：编辑器增加 Operation → 执行策略 → Role Grant → Validate/Publish 步骤；只显示 registry Operation，不显示 secret 或内部 endpoint。
- [ ] Step 4：实现版本列表、diff、禁用、归档和回滚；回滚文案明确为“创建新版本”。
- [ ] Step 5：实现审计按 Skill、用户、事件、时间和结果筛选，显示 request ID 和 deny reason，不显示敏感 payload。
- [ ] Step 6：运行测试、浏览器人工操作并提交。

~~~powershell
cd web/admin
npm test -- --run src/features/skills
npm run typecheck
npm run lint
npm run build
cd ../..
pytest web/admin/tests/t20_tool_skill_admin_playwright.py -m m2 -q
git add web/admin/src/features/skills web/admin/tests/t20_tool_skill_admin_playwright.py
git commit -m "feat: add secure tool skill admin operations"
~~~

**人工验收：** 登录 tenant-a 管理员，完成 Operation 绑定、角色授权、v1/v2、diff、禁用/归档和审计；换 employee 确认管理按钮不出现且 API 仍拒绝。

### Task M2-06：完成 Chat 权限过滤、异步状态、取消和产物下载

**Files:**

- Modify: web/admin/src/features/chat/api/skillApi.ts
- Modify: web/admin/src/features/chat/components/SkillsDrawer.tsx
- Modify: web/admin/src/features/chat/components/SkillRunCard.tsx
- Modify: web/admin/src/features/chat/pages/ChatPage.tsx
- Modify: web/admin/src/features/chat/types.ts
- Modify: server/app/api/v1/chat.py
- Create: server/tests/test_skill_chat_m2.py
- Modify: web/admin/tests/t21_tool_skill_chat_playwright.py

- [ ] Step 1：写失败 Chat 测试。列表只包含当前 tenant 中同时满足 SKILL_READ、published、enabled、Operation available 和 role grant 的 Skill；缺 SKILL_EXECUTE 时可读但执行 API 拒绝；跨租户 ID 不泄露存在性。
- [ ] Step 2：实现 SSE 状态解析和恢复，支持 queued、started、progress、result、artifact、error、done；断线后用 GET /api/v1/skill-executions/{id} 对账。
- [ ] Step 3：运行卡显示取消按钮、超时原因、失败码和 artifact 下载；取消请求只引用 execution ID。
- [ ] Step 4：运行前端和浏览器验证。

~~~powershell
cd web/admin
npm test -- --run src/features/chat
npm run typecheck
npm run lint
npm run build
cd ../..
pytest web/admin/tests/t21_tool_skill_chat_playwright.py -m m2 -q
git add web/admin/src/features/chat server/app/api/v1/chat.py server/tests/test_skill_chat_m2.py web/admin/tests/t21_tool_skill_chat_playwright.py
git commit -m "feat: add secure async tool skill chat flow"
~~~

**人工验收：** tenant-a 授权用户看到并执行；缺 SKILL_READ 看不到；缺 SKILL_EXECUTE 只能查看；长任务可取消；授权用户可下载 artifact，跨租户不能下载。

### Task M2-07：完成 M2 端到端、安全负向和 staging 发布验收

**Files:**

- Create: server/tests/e2e/test_m2_tool_skill_operational_loop.py
- Create: server/tests/security/test_tool_skill_m2_security.py
- Create: docs/development/v1.1/skills/tool-skill-m2-secure-operations-runbook.md
- Modify: server/tests/test_skill_release_acceptance.py
- Modify: web/admin/tests/t20_tool_skill_admin_playwright.py
- Modify: web/admin/tests/t21_tool_skill_chat_playwright.py

- [ ] Step 1：写 e2e，使用 tenant-a/tenant-b、真实 session、seed roles/permissions、fake knowledge-base.search 验证创建、绑定、授权、发布、读取、执行、版本、禁用、归档、取消、审计和产物。
- [ ] Step 2：写安全负向：过期 session、cross-tenant IDs、缺 SKILL_READ、缺 SKILL_EXECUTE、缺 role grant、伪造 version/Operation/role、审计失败、队列失败、timeout/cancel race、artifact replay。
- [ ] Step 3：写 staging runbook，包含 seed upgrade、迁移、Redis/Celery、flags、超时/取消、审计留存、artifact 清理、Connector unavailable 和回滚。
- [ ] Step 4：运行 M2 gate。

~~~powershell
$env:SKILLS_M1_LOCAL_DEMO_MODE = "false"
$env:SKILLS_M2_OPERATIONS_ENABLED = "true"
$env:SKILLS_M3_IMPORTS_ENABLED = "false"
$env:SKILLS_EXECUTION_DRIVER = "celery"

pytest server/tests/test_skill_permissions.py server/tests/test_skill_tenant_isolation.py -q
pytest server/tests/test_skill_connectors.py server/tests/test_skill_operations.py -q
pytest server/tests/test_skill_versions.py server/tests/test_skill_lifecycle.py -q
pytest server/tests/test_skill_execution_m2.py server/tests/test_skill_audit.py server/tests/test_skill_artifacts.py -q
pytest server/tests/security/test_tool_skill_m2_security.py -q
pytest server/tests/e2e/test_m2_tool_skill_operational_loop.py -q

cd web/admin
npm test -- --run src/features/skills src/features/chat
npm run typecheck
npm run lint
npm run build
cd ../..
pytest web/admin/tests/t20_tool_skill_admin_playwright.py -m m2 -q
pytest web/admin/tests/t21_tool_skill_chat_playwright.py -m m2 -q
git diff --check
~~~

- [ ] Step 5：完成 staging 人工演示、归档证据后提交并打标签。

~~~powershell
git add server/tests/e2e/test_m2_tool_skill_operational_loop.py server/tests/security/test_tool_skill_m2_security.py server/tests/test_skill_release_acceptance.py web/admin/tests/t20_tool_skill_admin_playwright.py web/admin/tests/t21_tool_skill_chat_playwright.py docs/development/v1.1/skills/tool-skill-m2-secure-operations-runbook.md
git commit -m "test: verify m2 secure tool skill operations"
git tag tool-skills-m2-secure-operations
~~~

**人工验收：** 按第 1 节完成真实登录、跨租户、权限、Operation、版本、异步、取消、审计和产物下载演示。

## 5. M2 退出条件

- [ ] 真实登录、会话过期、租户隔离和服务端权限链路通过自动化与人工验证。
- [ ] SKILL_READ、SKILL_EXECUTE、管理权限和 Skill 级角色授权均由服务端强制执行。
- [ ] 客户端只能选择服务端预注册 knowledge-base.search，不能注册任意 Operation 或传入 URL/SQL/凭据。
- [ ] 版本、diff、回滚新版本、禁用和归档可操作，已发布版本不可原地修改。
- [ ] Celery 执行、状态、进度、超时、取消、幂等、审计和 artifact download 可人工演示。
- [ ] 跨租户、未授权、Operation 不可用、审计失败、队列失败和下载越权均 fail closed。
- [ ] M2 focused suite、e2e、前端构建、Playwright、迁移和 runbook 全部通过。
- [ ] M2 可进入受控 staging/production；M1 local-demo flag 关闭后不存在未认证降级路径。

**M2 可演示结果：** 已登录用户在所属租户中看到自己有权执行的 Skill；管理员可以绑定受控 fake Operation 并按角色授权；执行过程可观察、可取消、可审计，产物只能被授权用户下载。
