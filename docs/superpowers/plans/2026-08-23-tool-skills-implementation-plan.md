# Tool Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax (- [ ]) for tracking.

**Goal:** 分三个能够独立验收的里程碑交付 Tool Skill 系统：M1 先完成仅供本地开发/测试使用的创建、编辑、发布、执行和 Chat 手动选择闭环；M2 再加入基础登录、租户隔离、`SKILL_READ` / `SKILL_EXECUTE` 权限校验、服务端预注册 fake Connector Operation、版本和安全运营；M3 最后加入收藏、默认参数、显示名称、排序、私有 `SkillPreset`、安全导入导出和生产治理。Chat 用户始终只能使用管理员发布的系统 Tool Skill，不能创建或共享真正的 Skill。

**Architecture:** Skill 只保存面向用户的能力定义和不可变版本，不携带可执行代码。M1 使用受本地回环保护的固定 `DemoSkillHandler`，不提供 Connector Operation 绑定；M2 切换为服务端预注册、不可由客户端扩展的 fake Connector Operation，并由统一执行服务锁定发布版本、租户、角色快照和操作契约；M3 在此基础上增加 Agent Skills 包导入、连接器运营和用户私有 `SkillPreset`。模型不得自动选择或调用 Skill。

**Tech Stack:** FastAPI、Pydantic、SQLAlchemy、Alembic、PostgreSQL/SQLite、Celery/Redis、jsonschema、PyYAML、React 19、TypeScript、Vite、TanStack Query、既有 Chat SSE 与 RBAC。

---

## 0. 第一期开工边界与不可违反的安全约束

本计划以 `docs/superpowers/specs/2026-08-19-skills-management-system-design.md` 为产品和接口基线，并按里程碑延后安全能力。实现时必须同时满足以下范围：

1. `skill_type` 数据库保留 `TOOL`、`PROMPT` 两个枚举值，但本计划的三个里程碑都只接受 `TOOL`；Prompt Skill 另行立项。
2. M1 不实现真实登录、真实租户隔离或 `SKILL_READ` / `SKILL_EXECUTE` 权限校验。M1 只能在显式开启 `SKILLS_M1_LOCAL_DEMO_MODE=true`、请求来自 loopback、身份为本地演示身份时运行；该模式不能部署到 staging/production。M2 才接入真实登录、租户上下文和服务端权限链路。
3. Chat 的交互方式固定为“打开 Skills 面板 → 按分类浏览 → 手动选择 Skill → 填写结构化参数 → 明确点击执行”。普通 Chat 文本、模型输出和客户端猜测都不能自动触发 Skill。
4. M1 不提供用户个性化持久化。收藏、显示名称、默认参数和排序只能在 M3 通过租户内用户私有 `SkillPreset` 实现；`SkillPreset` 不是 Skill 版本，不可共享、不可发布，也不能改变 Operation、角色、URL、SQL、凭据或安全策略。
5. 客户端请求体始终只允许 `skillId` 和结构化 `input`。M1 的服务端固定解析 `demo_handler_key=customer_report_search`；M2/M3 从服务端已发布版本解析 Connector Operation、租户连接、角色授权和策略。客户端不得传 `skillVersionId`、`connectorKey`、`operationKey`、`roleIds`、完整 URL、SQL 或凭据。
6. Agent Skills 导入包只作为 M3 草稿来源。导入预检拒绝脚本、可执行文件、路径穿越、符号链接、密钥模式、未知二进制、超大文件和压缩炸弹；系统永不加载或运行包内 `scripts/`。
7. M1 的安全底线是“本地模式不可对外暴露、固定 Handler 不读取网络/凭据/任意代码、控制字段白名单”；M2/M3 进一步要求权限、审计写入、Connector 状态、凭据引用、输入校验任一失败时 fail closed，不得降级成未审计调用。

## 里程碑交付策略

本计划不再把 Task 1–14 视为一次性大版本，而是把它们切成三个能够独立部署、独立回归、独立人工演示的交付里程碑。每个里程碑都必须满足“自动化测试通过 + 浏览器人工验收通过 + 数据迁移可升级/回滚 + 安全边界没有被绕过”四个条件，才允许进入下一个里程碑。

### 共同交付约束

1. **每个里程碑都有可运行的闭环。** M1 是“本地演示身份 → 管理后台创建/编辑/发布 → Chat 用户浏览/手动选择/填写/执行固定 Demo Handler → 返回安全结果”；M2 在同一条链路上加入登录、租户、权限、fake Connector Operation、版本、生命周期、长任务、审计和产物；M3 再补齐私有 Preset、导入导出和生产治理。
2. **数据库按阶段启用能力。** `0009_tool_skills.py` 可以为了向后兼容预建未来阶段所需的基础表和字段，但 M1 只启用分类、Skill、草稿/发布指针、执行和最小事件；M2 才启用真实租户上下文、角色授权、Connector/Operation 绑定、版本运营和审计/产物；M3 才启用 Preset、导入历史和完整治理字段。不能因为提前建表就把后续 API/UI 暴露到 M1。
3. **执行入口保持同一个服务接口。** M1 使用 `InlineDemoSkillExecutionDriver` 调用固定本地 Handler；M2 切换到 `CelerySkillExecutionDriver` 调用服务端预注册 fake Operation；两者都通过同一个 `SkillExecutionService`，客户端请求体不变。M3 只扩展 Operation 和运行治理，不重写 Chat 调用协议。
4. **M1 是明确的开发/测试模式，不是安全生产模式。** `LocalDemoIdentityMiddleware` 只接受 loopback 请求和固定演示身份，固定使用一个本地 Demo namespace；它不冒充登录，也不宣称提供租户隔离或 `SKILL_READ` / `SKILL_EXECUTE` 校验。M2 完成真实登录、租户隔离和服务端权限后，才允许进入受控 staging/production。
5. **功能开关只控制入口，不改变已经实现的服务端门禁。** 部署环境必须显式设置以下配置：

   | 配置键 | M1 | M2 | M3 |
   |---|---|---|---|
   | `SKILLS_M1_CORE_ENABLED` | `true` | `true` | `true` |
   | `SKILLS_M1_LOCAL_DEMO_MODE` | `true`（仅 loopback） | `false` | `false` |
   | `SKILLS_M2_OPERATIONS_ENABLED` | `false` | `true` | `true` |
   | `SKILLS_M3_IMPORTS_ENABLED` | `false` | `false` | `true` |
   | `SKILLS_EXECUTION_DRIVER` | `inline-demo` | `celery` | `celery` |

   关闭开关时，服务端返回统一的 `FEATURE_DISABLED` 错误；不能仅隐藏前端按钮后仍允许直接调用 API。
6. **每个里程碑单独拥有验收测试入口。** 新增三个服务端验收文件，并在已有浏览器验收文件中按 marker 分组：

   - `server/tests/e2e/test_m1_tool_skill_closed_loop.py`
   - `server/tests/e2e/test_m2_tool_skill_operational_loop.py`
   - `server/tests/e2e/test_m3_tool_skill_complete.py`
   - `web/admin/tests/t20_tool_skill_admin_playwright.py` 中的 `@pytest.mark.m1`、`@pytest.mark.m2`、`@pytest.mark.m3`
   - `web/admin/tests/t21_tool_skill_chat_playwright.py` 中的 `@pytest.mark.m1`、`@pytest.mark.m2`、`@pytest.mark.m3`

7. **里程碑之间使用独立提交和验收标签。** 每个里程碑的最后一个提交必须只包含该里程碑计划范围内的代码、迁移、测试和文档。推荐标签分别为 `tool-skills-m1-local-demo`、`tool-skills-m2-secure-operations`、`tool-skills-m3-production-complete`；标签建立前必须完成本文对应的退出条件。

---
## Milestone 1：Tool Skill 本地 Demo 最小闭环

**目标：** 在不引入真实登录、租户隔离、`SKILL_READ` / `SKILL_EXECUTE` 校验和 Connector Operation 绑定的前提下，交付一个仅限本地开发/测试使用的闭环：管理员可以创建、编辑、校验和发布 Tool Skill，Chat 演示用户可以按分类手动选择、填写结构化参数并执行固定 Demo Handler。

**交付结果：** 开发者启动本地服务并显式打开 `SKILLS_M1_LOCAL_DEMO_MODE`，使用本地演示身份 `system_admin` 创建“客户数据”分类和 `customer-report-search` Tool Skill；编辑器固定关联 `customer_report_search` Demo Handler，不显示 Connector Operation 选择器；发布后，`demo_employee` 在 Chat 的 Skills 面板中手动选择该 Skill、填写关键词并点击执行，页面显示结构化结果。任何非 loopback 请求、任意 Operation/角色/凭据注入和普通 Chat 自动调用都被拒绝。M1 不实现登录、租户隔离、真实权限、收藏、默认参数、显示名称、排序或 `SkillPreset`。

### M1 功能范围

| 领域 | 里程碑一交付内容 | 明确不在 M1 的内容 |
|---|---|---|
| Skill 合同 | TOOL 类型、`SKILL.md` 元数据映射、受限 JSON Schema、表单展示配置、执行策略上限 | PROMPT Skill、模型自动选择、自由脚本、可执行导入包 |
| 持久化 | 单一 local demo namespace 下的分类、Skill、初始草稿/发布指针、执行记录、最小事件记录 | 真实租户隔离、角色授权、版本历史/差异/回滚、SkillPreset |
| 管理后台 | Skills 列表、分类 CRUD、Tool Skill 编辑器、保存草稿、服务端校验、首次发布 | 登录页、Connector/Operation 管理或绑定、RBAC 授权矩阵、审计查询、导入/导出 |
| 执行引擎 | `InlineDemoSkillExecutionDriver`、固定 `customer_report_search` Handler、输入校验、结果脱敏、结果大小上限 | 预注册 Connector Operation、Celery 长任务、超时、取消、重试、产物下载、限流/并发控制 |
| Chat | 分类浏览、可用 Skill 列表、结构化参数表单、手动确认执行、结果卡片 | 自动触发、长任务进度、取消按钮、产物卡片 |
| 用户个性化 | 只支持 Schema 中声明的服务端默认值展示，不保存用户个性化数据 | 收藏、显示名称、排序、默认参数保存、共享 Skill、发布 SkillPreset |
| 安全边界 | loopback + local demo flag、固定演示身份、请求字段白名单、固定 Handler 不访问外部资源 | 基础登录、租户隔离、`SKILL_READ` / `SKILL_EXECUTE`、可配置 RBAC、生产部署 |

### M1 技术切片和任务映射

1. **合同与迁移：Task 1、Task 2。** 先落地 `ToolInputSchema`、M1 管理请求、`SkillAvailableDefinition` 和 `SkillRunCreateRequest`，再执行 `0009_tool_skills.py`。M1 只启用一个 local demo namespace 和一个可发布版本；为 M2 预留版本、授权、Connector、审计、产物和 Preset 字段，但不在 M1 路由中开放。
2. **本地演示边界：Task 3 不在 M1 实现。** 用 `LocalDemoIdentityMiddleware` 将 `system_admin`/`demo_employee` 映射为本地演示身份，拒绝非 loopback 请求；不调用真实登录服务，不执行 `SKILL_READ` / `SKILL_EXECUTE`，也不把演示身份当作生产角色。M1 的管理 API 和 Chat API 都必须检查 local demo flag，关闭或脱离 loopback 即返回 `FEATURE_DISABLED`/`LOCAL_DEMO_ONLY`。
3. **固定 Demo Handler：Task 4 不在 M1 实现。** 在执行层实现一个代码内固定的 `customer_report_search` Handler，输入只允许 `query: string` 和有上限的 `limit: integer`，返回固定的本地测试结果；它不读取真实网络、SQL、文件、凭据或用户传入的 Handler 名称。M1 编辑器不显示 Connector/Operation 下拉框，Skill 版本由服务端写入固定的内部 handler 标识。
4. **管理域：Task 5 的 M1 slice。** 实现分类新增/编辑/停用、Skill 新建、草稿元数据编辑、输入 Schema 编辑、服务端校验和首次发布。已发布 Skill 的再次编辑只允许更新当前编辑草稿；不提供版本历史、角色授权、Operation 绑定、回滚和归档按钮。
5. **执行引擎：Task 8 的 M1 slice。** 实现 `InlineDemoSkillExecutionDriver` 和统一的 `SkillExecutionService`。流程为“local demo gate → 查当前发布版本 → 校验输入 → 创建执行 → 写入 started 事件 → 调用固定 Handler → 脱敏结果 → 写入 done/result 事件 → 返回 SSE 事件序列”。M1 至少持久化 `skill_run_started`、`skill_run_status`、`skill_run_result`、`skill_run_done` 和 request ID。
6. **Chat 后端：Task 9 的 M1 slice。** 实现本地可用分类、可用 Skill 定义和 `POST /chat/sessions/{session_id}/skill-runs`。M1 在 inline driver 下快速发完同一条 SSE 流；若前端环境不支持流式测试，允许通过 `GET /skill-executions/{execution_id}` 查询同一份结果。请求体只允许 `skillId` 和 `input`，不能借此绕过 local demo gate。
7. **管理后台：Task 10、Task 11 的 M1 slice。** 先完成列表和分类管理，再完成三步编辑器：基本信息 → 参数 Schema → 校验/发布。编辑器显示类型 TOOL、当前状态、阻断错误和发布确认；不得渲染或接受 Connector URL、密钥、自由 SQL、脚本、Operation key 或角色 ID。
8. **Chat UI：Task 13 的 M1 slice。** 在 Skills 抽屉中按分类展示可用 Skill；进入详情后展示描述、输入限制和结构化表单；执行按钮必须是用户明确点击，不能由普通 Chat 文本触发。执行完成后显示安全结果、失败码和 request ID；不显示收藏、默认参数、显示名称或排序控件。
9. **M1 安全验收：Task 14 的 M1 slice。** 验证非 loopback 请求被拒绝，关闭 local demo flag 后所有管理/执行入口被拒绝，并对伪造 `skillVersionId`、`connectorKey`、`operationKey`、`roleIds`、`url`、`sql`、`credential` 的请求返回 4xx 且固定 Handler 调用次数为 0。

### M1 自动化验证

从 `D:\codeproject\python\lingxi` 执行：

```powershell
$env:SKILLS_M1_CORE_ENABLED = "true"
$env:SKILLS_M1_LOCAL_DEMO_MODE = "true"
$env:SKILLS_M2_OPERATIONS_ENABLED = "false"
$env:SKILLS_M3_IMPORTS_ENABLED = "false"
$env:SKILLS_EXECUTION_DRIVER = "inline-demo"

pytest server/tests/test_skill_contracts.py -q
pytest server/tests/test_skill_models.py -m m1 -q
pytest server/tests/test_skills_api.py -m m1 -q
pytest server/tests/test_skill_execution.py -m m1 -q
pytest server/tests/test_skill_sse.py -m m1 -q
pytest server/tests/test_skill_chat_api.py -m m1 -q
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
```

**M1 自动化通过标准：** M1 用例不得依赖真实登录、租户、角色权限或 Connector registry；后端 focused suite、M1 e2e、前端单元/类型/构建和两个浏览器 marker 全部 PASS；`test_m1_tool_skill_closed_loop.py` 至少验证本地管理员创建/发布、本地 Chat 演示用户可见/可执行、结果事件顺序、普通 Chat 不自动调用、非 loopback 被拒绝和伪造控制字段拒绝。

### M1 人工验收脚本

在本地开发机启动服务，设置 `SKILLS_M1_LOCAL_DEMO_MODE=true`，使用浏览器提供的本地演示身份切换器选择 `system_admin` 或 `demo_employee`。M1 不使用登录页，不接入真实租户，不连接真实外部系统。

1. **验证本地模式边界。** 以 `system_admin` 进入本地 Skills 后台，确认页面显示“Local Demo”；从非 loopback 地址或关闭 local demo flag 后访问同一页面，服务端返回 `LOCAL_DEMO_ONLY`/`FEATURE_DISABLED`，而不是打开管理页面。
2. **创建分类。** `system_admin` 打开“分类管理”，新增“客户数据”，填写 key `customer-data`、名称和描述，保存后在列表中看到“启用”；编辑名称并刷新，确认修改持久化。
3. **创建 Skill 草稿。** 打开“Skills 列表”→“新建 Tool Skill”，填写 key `customer-report-search`、名称“客户报表查询”、描述和分类，确认类型固定显示 TOOL 且不能切换为 PROMPT。
4. **确认 M1 不暴露 Connector。** 在编辑器中确认只有固定的“客户报表查询 Demo Handler”提示，没有 Connector、Operation、URL、SQL、凭据或角色选择器；尝试粘贴未知 Operation key，页面和服务端都拒绝。
5. **配置输入表单。** 在参数 Schema 步骤添加必填 `query` 字符串和可选 `limit` 整数，设置 Schema 默认值 `10`；尝试添加 `password`、`url` 或 `sql` 字段，页面显示阻断校验且保存请求被服务端拒绝。
6. **保存并发布。** 点击“保存草稿”，返回列表确认状态为“草稿”；点击“校验”，确认无阻断错误；点击“发布”并确认弹窗，列表状态变为“已发布”。刷新后 Skill 仍然存在。
7. **Chat 浏览和手动选择。** 切换为 `demo_employee`，打开 Chat → Skills，按“客户数据”分类看到“客户报表查询”；打开详情看到描述和 `query`/`limit` 表单。普通 Chat 输入“请自动调用客户报表查询”不会创建 Skill 执行。
8. **验证 Schema 默认值。** 重新打开 Skill 详情，确认 `limit` 显示 Schema 默认值 `10`；修改输入后离开并重新打开，确认 M1 不保存用户个性化输入，也不显示收藏、显示名称或排序控件。
9. **执行并查看结果。** 填写 `query=华东客户`，点击“执行”并确认，看到 started/status/result/done 对应的运行卡片和固定 Demo Handler 返回的结构化结果。页面显示 request ID，但不显示内部地址、凭据、堆栈或原始日志。
10. **安全负向操作。** 使用浏览器开发者工具在请求体增加 `skillVersionId`、`connectorKey`、`operationKey`、`roleIds`、`url`、`sql` 或 `credential`，服务端返回 400/422 且 Handler 没有新增调用；从非 loopback 重放请求也必须被拒绝。

### M1 退出条件和演示包

- [ ] `0009_tool_skills.py` 在空数据库和现有开发数据库上都能升级，既有业务测试无回归。
- [ ] 管理员创建/编辑/发布和 Chat 浏览/选择/执行的本地 Demo 闭环可在本地一键启动后完成。
- [ ] M1 的所有自动化命令通过，且没有被 `xfail`、跳过或仅依赖人工判断的关键断言。
- [ ] 人工验收脚本 1–10 全部通过并保存截图/录屏到 `docs/development/v1.1/acceptance/tool-skills/m1/`。
- [ ] 服务端在 local demo flag 关闭、非 loopback 或非法控制字段时 fail closed。
- [ ] M1 没有登录页、真实租户隔离、`SKILL_READ` / `SKILL_EXECUTE` 校验、Connector Operation 绑定或 SkillPreset API/UI；M1 标签明确标注为 local demo，不得部署到 staging/production。

**M1 可演示结果：** 开发者可以在本地从空白分类开始创建一个 Tool Skill，一名本地演示用户在 Chat 中按分类手动选择它，填写结构化参数并得到结果；这个结果可重复、可自动化测试，但 M1 不冒充真实身份、租户或权限系统。

---
## Milestone 2：基础安全与受控执行 Tool Skill 闭环

**目标：** 把 M1 的本地 Demo 闭环升级为第一个可进入受控 staging/production 的闭环：加入基础登录、租户隔离、`SKILL_READ` / `SKILL_EXECUTE` 服务端校验、管理员 `SKILL_MANAGE`/`SKILL_CATEGORY_MANAGE` 校验、服务端预注册 fake Connector Operation、版本和生命周期、长任务控制、审计、产物下载及 RBAC/角色授权。

**交付结果：** 用户通过真实登录进入所属租户；管理员在租户内创建或升级 Tool Skill，编辑器可以从服务端白名单绑定 `knowledge-base.search` fake Connector Operation；管理员按租户角色授予执行权限。Chat 用户只能看到同时满足 `SKILL_READ` 和 `SKILL_EXECUTE`、属于当前租户、处于已发布且启用状态、Connector/Operation 可用的 Skill。长任务能够显示状态和进度，用户可以取消；执行超时、审计写入失败、权限不匹配和产物越权下载都能安全失败。M2 不实现收藏、默认参数、显示名称或排序。

### M2 功能范围

| 领域 | 里程碑二交付内容 | M2 仍不包含的内容 |
|---|---|---|
| 登录与身份 | 基础登录、会话/token 校验、当前用户和当前租户上下文、登出和过期处理 | SSO、复杂组织同步、多因子认证运营 |
| 租户隔离 | 所有 Skill、分类、版本、Connector 连接、执行、事件和产物按 `tenant_id` 隔离；跨租户 ID/key 不可解析 | 跨租户共享 Skill、跨租户执行 |
| 权限 | 服务端强制校验 `SKILL_READ`、`SKILL_EXECUTE`、`SKILL_MANAGE`、`SKILL_CATEGORY_MANAGE`、`SKILL_CONNECTOR_MANAGE`、`SKILL_AUDIT_READ`；按租户角色授权 Skill 版本 | Chat 用户创建或共享 Skill |
| Connector | 服务端预注册的 `knowledge-base.search` fake Connector Operation；管理员可绑定并配置安全契约 | 任意 URL、自由 SQL、用户上传代码、多 Connector 生产连接管理 |
| 版本 | 不可变版本、版本列表、差异、发布、回滚为新版本、执行锁定版本 | Prompt Skill 的版本与模型策略 |
| 生命周期 | 禁用、重新启用、归档（归档为终态）；保留历史执行 | 删除历史、物理清理执行数据 |
| 执行 | Celery/Redis 队列、状态机、超时、取消、幂等、并发和输出基础限制 | 高级重试策略、跨 Skill 编排 |
| 审计 | 管理、授权、执行、取消、超时、下载事件的脱敏记录和查询页面 | SIEM/SOC 外部联动 |
| 产物 | 白名单产物存储、二次鉴权、短时下载令牌、过期清理 | 任意文件浏览或任意路径下载 |
| 管理后台 | 版本历史/差异、Operation 绑定、发布/回滚/停用/归档确认、角色授权、审计查询、登录态和租户上下文 | 包导入、连接器连接配置和多 Operation 管理、用户个性化入口 |
| Chat | 运行中状态、进度、取消、终态、错误、产物下载 | 收藏、显示名称、默认参数、排序和完整 `SkillPreset` |

### M2 技术切片和任务映射

1. **登录、租户和权限：Task 3、Task 5、Task 9 的 M2 slice。** 接入项目现有登录/会话机制，建立当前用户、当前租户和角色上下文；所有 Skill 查询、执行、版本、事件、产物和 Connector 查询必须带服务端 `tenant_id` 条件。服务端以 `SKILL_READ` 控制可用列表、以 `SKILL_EXECUTE` 控制执行入口，管理动作再校验对应的 `SKILL_MANAGE`/分类/审计/Connector 权限。前端隐藏按钮不算安全控制。
2. **fake Connector Operation：Task 4、Task 5、Task 11 的 M2 slice。** 启用 `SKILLS_M2_OPERATIONS_ENABLED` 后，注册只读的 `knowledge-base.search` fake Operation，接受 `{ "query": string, "limit": integer }`，返回固定格式的本地测试结果。Skill 版本必须保存服务端解析出的 `connector_operation_id` 和 Operation 契约；客户端只能提交 `skillId` 和业务输入，不能提交 Operation key。M2 的编辑器才显示 Operation 白名单选择器。
3. **角色授权矩阵：Task 3、Task 5 的 M2 slice。** 移除 M1 的固定演示身份限制，管理员可以为当前租户角色授予某个 Skill 版本的执行权。可用列表和执行服务共同使用 `authenticated_user AND same_tenant AND user_has_permission(SKILL_READ/SKILL_EXECUTE) AND active_skill AND active_category AND published_version AND role_grant AND active_operation` 公式；任一条件失败都返回安全错误，不能泄露资源是否存在。
4. **版本和生命周期：Task 5 的 M2 slice。** 编辑已发布版本时创建新的不可变草稿；发布后旧版本仍可被历史执行引用但不再用于新执行。版本差异只返回脱敏字段；回滚不是修改旧版本，而是复制目标版本内容创建新草稿并重新校验。归档是终态，停用阻止新执行但保留列表和执行历史。
5. **异步执行：Task 8 的 M2 slice。** 用 `CelerySkillExecutionDriver` 替换 M1 driver，使用同一 `SkillExecutionService`。实现 `PENDING → VALIDATING → QUEUED → RUNNING → SUCCEEDED/FAILED/TIMED_OUT/CANCELED`，每个状态转换写入事件；队列提交失败不得伪造成功。
6. **超时和取消：Task 8 的 M2 slice。** 在 Operation 契约和 Skill execution policy 的较小者上设置超时；取消只向声明支持取消的 Operation 发送 cancel token，不支持时标记取消请求并等待安全终止。超时和取消必须阻止后续成功结果覆盖终态。
7. **审计和产物：Task 8、Task 9、Task 12 的 M2 slice。** `skill_audit_service.py` 写入发布、停用、归档、授权变更、执行、取消、超时、下载和失败事件；输入、结果、凭据、连接器内部地址和 traceback 均按 schema 脱敏。审计写入失败时，管理变更和执行创建均 fail closed。产物只允许注册 Operation 通过 `SkillArtifactService` 写入白名单目录/对象存储，下载端点再次检查租户、执行所有者、当前角色和产物未过期状态。
8. **后台和 Chat UI：Task 10、Task 11、Task 12、Task 13 的 M2 slice。** 管理后台新增登录态/租户上下文、版本历史、差异、Operation 绑定、角色授权和生命周期动作；Chat 运行卡片显示排队、执行、进度、失败、超时、取消，成功后显示产物文件名、大小和下载按钮。M2 不显示收藏、默认参数、显示名称或排序控件。
9. **M2 集成验收：Task 14 的 M2 slice。** 增加跨用户、跨角色、跨租户、未登录、过期会话、无 `SKILL_READ`、无 `SKILL_EXECUTE`、未授权角色、Operation 不可用和审计写入失败的负向用例；确认客户端不能通过伪造版本/Operation/角色字段绕过服务端。

### M2 自动化验证

从 `D:\codeproject\python\lingxi` 执行：

```powershell
$env:SKILLS_M1_CORE_ENABLED = "true"
$env:SKILLS_M1_LOCAL_DEMO_MODE = "false"
$env:SKILLS_M2_OPERATIONS_ENABLED = "true"
$env:SKILLS_M3_IMPORTS_ENABLED = "false"
$env:SKILLS_EXECUTION_DRIVER = "celery"

pytest server/tests/test_skill_contracts.py -q
pytest server/tests/test_skill_models.py -m "m1 or m2" -q
pytest server/tests/test_skill_permissions.py -m m2 -q
pytest server/tests/test_skill_connectors.py -m m2 -q
pytest server/tests/test_skill_operations.py -m m2 -q
pytest server/tests/test_skills_api.py -m m2 -q
pytest server/tests/test_skill_execution.py -m "m1 or m2" -q
pytest server/tests/test_skill_sse.py -m "m1 or m2" -q
pytest server/tests/test_skill_chat_api.py -m m2 -q
pytest server/tests/security/test_skill_security.py -m "m1 or m2" -q
pytest server/tests/e2e/test_m1_tool_skill_closed_loop.py -q
pytest server/tests/e2e/test_m2_tool_skill_operational_loop.py -q

cd web/admin
npm test -- --run src/features/skills src/features/chat
npm run typecheck
npm run lint
npm run build
cd ../..

pytest web/admin/tests/t20_tool_skill_admin_playwright.py -m "m1 or m2" -q
pytest web/admin/tests/t21_tool_skill_chat_playwright.py -m "m1 or m2" -q
git diff --check
```

**M2 自动化通过标准：** M1 本地 Demo 的功能回归继续通过；M2 测试覆盖登录、会话过期、租户隔离、`SKILL_READ`/`SKILL_EXECUTE`、角色授权、fake Operation 绑定、版本、状态机、超时、取消、审计、产物下载和越权拒绝；Playwright 能稳定等待队列状态，不依赖固定 sleep；同一 `Idempotency-Key` 不会创建重复执行。

### M2 人工验收脚本

使用 M1 已发布的 `customer-report-search`，在租户 A 再准备一个由 fake Connector 模拟 8 秒延迟和可取消能力的 `customer-report-export` Skill。准备租户 A、租户 B，以及 `system_admin`、`report_viewer`、`report_operator` 和无权限用户，所有账号都通过真实登录页进入系统。

1. **登录与租户上下文。** `system_admin` 登录租户 A，确认页面显示当前用户和租户；退出后使用租户 B 账号登录，确认不会看到租户 A 的 Skills、分类、执行或审计记录。未登录、过期会话访问 Skills API 都返回统一 401。
2. **绑定 fake Operation。** 管理员打开 M1 的 `customer-report-search` 草稿/新版本，确认编辑器现在出现服务端白名单中的 `knowledge-base.search`；选择并保存后，页面显示输入/输出契约。尝试输入未知 Operation key、URL、SQL 或凭据均被服务端拒绝。
3. **创建新版本。** 管理员修改表单字段描述或默认 `limit`，保存后确认产生“草稿 v2”；版本列表中 v1 仍显示“已发布”，v1 的内容和 content hash 不变。
4. **查看差异并发布。** 打开 v1/v2 差异，确认只展示业务字段和安全策略摘要，不展示凭据、连接器内部地址或原始输入；发布 v2 后，新执行锁定 v2，历史 v1 执行仍显示 v1。
5. **验证读取/执行权限和角色授权。** 只给 `report_viewer` 授权 `customer-report-search`，让 viewer 登录 Chat 能看到并执行；撤销 `SKILL_EXECUTE` 或 Skill 角色授权后刷新，Skill 从可用列表消失，直接猜 ID 返回 403/404；只有 `SKILL_READ` 但没有 `SKILL_EXECUTE` 的账号不能执行。
6. **停用和归档。** 管理员停用 Skill 并确认，Chat 列表不再显示且新执行被拒绝；历史执行和审计记录仍可查看。归档后尝试重新打开旧管理链接，页面显示只读终态，不能直接编辑或发布。
7. **执行长任务和取消。** 启用 `customer-report-export`，Chat 用户填写参数并点击执行，运行卡片依次显示 queued/running/progress；点击“取消”后显示 canceled，fake Connector 收到 cancel token，不能再转为 succeeded。
8. **验证超时。** 把测试策略设置为 2 秒，执行 8 秒 Operation，页面显示 timed out；审计中有 timeout 事件，错误只显示安全错误码和建议，不显示线程堆栈、连接字符串或内部路径。
9. **验证审计和产物下载。** 管理员进入“Skills → 审计”，按操作人、Skill 和时间范围筛选，看到发布、授权、执行、取消、超时事件；让 fake Operation 生成 `customer-report.csv`，合法用户可以下载，换成未授权用户、另一租户、修改 artifact ID 或过期令牌均被拒绝。
10. **验证 fail closed 和边界。** 把审计写入模拟为失败，新的执行不进入队列，接口返回 request ID 和安全错误；普通 Chat 文本不能创建 Skill、改变授权或调用未展示的 Operation，重复 `Idempotency-Key` 只产生一个 execution。

### M2 退出条件和演示包

- [ ] M1 本地 Demo 的功能回归在 `SKILLS_EXECUTION_DRIVER=celery` 和真实登录链路下继续通过，且客户端调用协议不变。
- [ ] 基础登录、会话过期、租户隔离、`SKILL_READ` / `SKILL_EXECUTE`、RBAC 和角色授权均有服务端测试与浏览器测试，不能仅靠前端隐藏按钮通过。
- [ ] 预注册 fake Connector Operation 绑定、版本、归档、超时、取消、审计、产物下载均有自动化测试和人工操作证据。
- [ ] 人工验收脚本 1–10 全部通过并保存截图/录屏到 `docs/development/v1.1/acceptance/tool-skills/m2/`。
- [ ] 任何新执行都经过用户、租户、角色、Connector 状态和审计写入检查；历史执行只读且可追溯到锁定版本。
- [ ] 产物下载不会泄露存储 key、凭据、内部 URL 或其他租户数据；超时和取消不会覆盖已写入终态。
- [ ] M2 是第一个允许进入受控 staging/production 的发布标签；在此之前不得把 M1 local demo 部署到共享环境。

**M2 可演示结果：** 同一个 Tool Skill 可以在真实登录和租户边界内被授权、迭代、运行、取消、审计和下载产物；未登录、无权限、跨租户或客户端注入都无法绕过服务端控制。

---
## Milestone 3：用户个性化、完整 Tool Skill 能力和生产治理

**目标：** 在 M2 的安全运营闭环上补齐用户私有 Skill 个性化能力——收藏、显示名称、默认参数、排序和完整 `SkillPreset`——并增加 Agent Skills 包导入/导出、Connector 管理、多种受控 Operation、健康检查、重试/限流/并发治理、结果脱敏策略和完整发布运行手册。

**交付结果：** 用户可以在不改变系统 Skill 权限和执行定义的前提下收藏已授权 Skill、设置个人显示名称、保存默认参数和调整显示顺序；这些配置只对当前用户、当前租户生效。管理员可以安全预检并导入符合 Agent Skills 规范的 `SKILL.md` 包，把包中的描述映射到平台白名单 Operation 后生成草稿；可以管理租户连接和健康状态；可以在不开放脚本执行、任意 URL、自由 SQL 或包内凭据的前提下运行更多受控业务动作。

### M3 功能范围

| 领域 | 里程碑三交付内容 | 明确边界 |
|---|---|---|
| 用户个性化 | 私有 `SkillPreset`：收藏、显示名称、默认参数、排序；按用户和租户隔离，随已发布版本重新校验 | 不创建共享 Skill，不发布 Preset，不改变 Operation/角色/策略 |
| 包管理 | ZIP 预检、恶意包拒绝、冲突策略、导入草稿、脱敏导出、导入历史 | 永不执行包内 `scripts/`，不安装依赖，不加载插件 |
| Connector 管理 | 高权限管理员配置租户连接、健康检查、启停和安全状态 | 凭据只存引用，不在 Skill 或导出包中保存明文 |
| Operation | `database-readonly.run-template`、`internal-http.call-registered`、`file-processing.transform`、`ticketing.search/create/update` 的服务端注册和契约测试 | 不允许客户端注册 Operation、用户传完整 URL/SQL/HTTP method/header |
| 运行治理 | 重试策略、速率限制、并发配额、队列优先级、保留期、连接器熔断 | 不做跨 Skill 自主编排，不由模型自动调用 |
| 结果与审计 | 字段级脱敏、敏感输出检测、审计高级查询、健康/失败指标、告警和运行手册 | 不把原始凭据、traceback 或内部连接信息返回 Chat |
| 管理后台 | Preset 运营支持、导入/导出、Connector、Operation 映射、连接健康、运行统计和高级审计 | 仍不开放 Chat 用户创建共享 Skill |
| 用户侧 | Preset 完整管理、重试提示、限流提示、健康状态提示、产物/结果体验收 | Prompt Skill 和自动选择留到后续独立阶段 |
| 后续增强 | 私有 Skill 草稿和管理员审核流可作为独立 feature flag 设计；只产生用户私有草稿，不改变共享 Tool Skill 的发布权限 | 不作为 M3 基础闭环的完成条件，避免扩大当前权限边界 |

### M3 技术切片和任务映射

1. **私有 SkillPreset：Task 7、Task 13。** 只允许引用 M2 已发布且当前用户有权读取/执行的系统 Skill，保存 `isFavorite`、`displayName`、`defaultInput`、`displayOrder` 四类字段。每次读写先解析当前发布版本并按最新 Schema 校验默认参数；Skill 停用、归档、权限撤销或版本变更时重新校验并标记失效，不能静默提交旧字段。查询必须同时过滤 `tenant_id` 和 `user_id`，不允许通过 Preset 改变 Connector、Operation、角色、URL、SQL、凭据或执行策略。
2. **安全导入/导出：Task 6。** 先对 ZIP 条目做路径、符号链接、脚本、可执行文件、密钥模式、压缩炸弹、未知二进制和大小预检，再提取到临时目录；只解析单个 `SKILL.md`、`references/` 和 `assets/`。导入始终创建草稿，管理员必须重新选择平台 Operation、分类和角色授权；导出只包含规范化的 Skill 描述和安全资源。
3. **Connector 管理：Task 4 的剩余 slice、Task 12。** 增加租户连接配置、加密凭据引用、健康检查和启停 UI；健康检查失败时新执行 fail closed，普通 Chat 不受影响。所有连接器变更写入审计，管理员 UI 只显示安全连接状态。
4. **多 Operation 契约：Task 4。** 每个 Operation 以 `OperationProtocol` 注册输入/输出 JSON Schema、side-effect 等级、超时上限、取消能力、产物能力和脱敏器；为 readonly database、registered internal HTTP、file processing 和 ticketing Operation 分别编写 fake adapter 和安全测试。
5. **运行治理：Task 8、Task 9。** 实现按租户/用户/Skill 的并发和速率限制、指数退避重试、不可重试错误分类、连接器熔断、队列优先级和执行/产物保留清理任务；重试必须新建 execution 并保留 `retry_of_execution_id`，不能覆盖原执行。
6. **管理后台补齐：Task 10、Task 11、Task 12。** 完成 Preset 运营只读统计、导入预检报告、冲突选择、Operation 映射、连接器管理、健康检查、导出、审计高级筛选和运行统计；所有危险操作仍使用确认弹窗，浏览器不能直接上传可执行包或调用任意接口。
7. **Chat 体验补齐：Task 13。** 完成收藏、显示名称、默认参数、排序的完整入口；增加可重试错误提示、限流/熔断提示、产物过期提示、结果字段脱敏展示和窄屏/键盘无障碍体验。Preset 保存失败时不得影响原有 Skill 执行，旧 Preset 也不得绕过 M2 的权限校验。
8. **发布治理：Task 14。** 生成运行手册、监控指标、告警阈值、备份/恢复和数据保留策略，执行安全攻击测试、全量 E2E、迁移升级/回滚和性能基线；Prompt Skill 不纳入 M3 发布标签。

### M3 自动化验证

```powershell
$env:SKILLS_M1_CORE_ENABLED = "true"
$env:SKILLS_M1_LOCAL_DEMO_MODE = "false"
$env:SKILLS_M2_OPERATIONS_ENABLED = "true"
$env:SKILLS_M3_IMPORTS_ENABLED = "true"
$env:SKILLS_EXECUTION_DRIVER = "celery"

pytest server/tests/test_skill_contracts.py -q
pytest server/tests/test_skill_models.py -m "m1 or m2 or m3" -q
pytest server/tests/test_skill_permissions.py -m "m2 or m3" -q
pytest server/tests/test_skill_connectors.py -m "m2 or m3" -q
pytest server/tests/test_skill_operations.py -m "m2 or m3" -q
pytest server/tests/test_skills_api.py -m "m1 or m2 or m3" -q
pytest server/tests/test_skill_import.py -m m3 -q
pytest server/tests/test_skill_preset.py -m m3 -q
pytest server/tests/test_skill_execution.py -m "m1 or m2 or m3" -q
pytest server/tests/test_skill_sse.py -m "m1 or m2 or m3" -q
pytest server/tests/test_skill_chat_api.py -m "m1 or m2 or m3" -q
pytest server/tests/security/test_skill_security.py -m "m1 or m2 or m3" -q
pytest server/tests/e2e/test_m1_tool_skill_closed_loop.py -q
pytest server/tests/e2e/test_m2_tool_skill_operational_loop.py -q
pytest server/tests/e2e/test_m3_tool_skill_complete.py -q
pytest server/tests/test_skill_release_acceptance.py -q

cd web/admin
npm test -- --run src/features/skills src/features/chat
npm run typecheck
npm run lint
npm run build
cd ../..

pytest web/admin/tests/t20_tool_skill_admin_playwright.py -m "m1 or m2 or m3" -q
pytest web/admin/tests/t21_tool_skill_chat_playwright.py -m "m1 or m2 or m3" -q
git diff --check
```

**M3 自动化通过标准：** Preset 隐私/版本失效测试、包安全测试、Connector registry、全量浏览器场景、类型检查、构建、迁移和性能基线全部通过；包安全测试必须证明“拒绝前不提取、不执行、不写入业务数据”；任何 Operation 都只能通过服务端 registry 调用，任意安全测试失败都阻止发布标签。

### M3 人工验收脚本

1. **管理私有个性化入口。** 用 M2 已授权的 Chat 用户登录，打开 Skills 面板，确认每个个性化操作都只作用于当前用户；管理员后台不能替用户创建 Preset，也不能把 Preset 发布为共享 Skill。
2. **收藏和显示名称。** 用户收藏 `customer-report-search`，设置显示名称“我的客户查询”；刷新、重新登录后名称和收藏状态仍在，另一个同租户用户看不到该变化，管理员也不能在系统 Skill 名称上看到用户私有覆盖。
3. **默认参数。** 用户保存 `limit=10` 和其他合法字段为默认参数；重新打开 Skill 表单时自动填充。尝试保存 `connectorKey`、`operationKey`、`roleIds`、URL、SQL、credential 等字段，服务端拒绝且原 Preset 不被破坏。
4. **排序。** 用户收藏多个 Skill 并设置排序，桌面和窄屏下 Skills 面板都按该用户顺序展示；删除排序或取消收藏后恢复系统默认顺序。
5. **版本失效处理。** 管理员发布新版本并删除/修改一个输入字段，用户再次打开 Skill 时默认参数被重新校验；不兼容字段被标记为失效并要求用户确认，不能静默执行旧输入。
6. **导入合法 Agent Skills 包。** 管理员打开“导入”，上传 `customer-report-export` fixture ZIP，先看到预检报告和 manifest 摘要；选择当前租户的分类和受控 Operation 后应用，列表出现“未发布草稿”，不会直接发布。
7. **拒绝恶意包。** 依次上传包含 `scripts/run.py`、路径穿越、符号链接、`.env`、私钥文本、超大压缩比和未知二进制的测试包；每次都在解压前得到阻断报告，服务器没有脚本进程、临时业务 Skill 或敏感日志。
8. **冲突处理和连接器健康。** 再导入同一 key，选择“新建 Skill”“新建草稿版本”“取消”分别验证结果；配置 fake 租户连接并执行健康检查，状态切换为 unavailable 时新执行被安全拒绝，恢复后可重新执行，普通 Chat 文本正常工作。
9. **受控 Operation、结果与重试。** 选择 registered internal HTTP、只读数据库或 file-processing fake Operation，表单只能选择服务端注册的 service/template key；触发可重试错误时，Chat 显示安全重试按钮，重试产生新的 execution 并链接原 execution，超过配额后显示限流提示。
10. **高级审计和发布恢复。** 在审计页筛选导入、连接器健康、重试、限流、Preset 变更和结果脱敏事件；按运行手册执行迁移升级、备份恢复、功能开关关闭和重新开启，确认关闭导入开关时 API/UI 都拒绝导入且不丢失 M1/M2 已发布 Skill。

### M3 退出条件和演示包

- [ ] 收藏、显示名称、默认参数、排序和私有 `SkillPreset` 均有服务端、前端、隐私和版本失效测试，并完成 1–5 步人工验收。
- [ ] 合法包导入、恶意包拒绝、冲突处理、脱敏导出、Connector 健康和多 Operation 均有自动化与人工验收记录。
- [ ] 全量安全测试确认没有脚本执行、任意 URL、自由 SQL、包内凭据、跨租户访问、未授权下载或模型自动调用路径。
- [ ] 运行手册、监控/告警、数据保留、备份恢复和故障处理文档已提交到 `docs/development/v1.1/skills/`。
- [ ] M1/M2 的数据库、API、浏览器用例在 M3 配置下继续通过，且关闭 M3 开关不会影响已发布 Skill 的读取、执行和已有用户 Preset 的安全读取。
- [ ] M3 标签建立后，Prompt Skill 另行立项，不把 Prompt Skill 混入本 Tool Skill 交付。

**M3 可演示结果：** 用户可以安全地个性化自己有权限使用的 Skill；管理员可以从安全的 Agent Skills 包得到一个可审查草稿，将其映射到平台受控 Operation 后发布；系统能够在连接器异常、恶意包、权限变化和资源压力下保持可解释、可审计、fail closed。

---
## Milestone Acceptance Matrix

| 验收项 | M1 本地 Demo 闭环 | M2 基础安全与受控执行 | M3 个性化与生产治理 |
|---|---|---|---|
| 管理员身份 | 仅 loopback 的本地演示身份；不是真实登录 | 基础登录、会话过期、`SKILL_MANAGE`/分类权限校验 | 高权限 Connector/导入/审计分层 |
| 租户与权限 | 单一 local demo namespace；不宣称租户隔离 | 真实租户隔离、`SKILL_READ` / `SKILL_EXECUTE`、角色授权和服务端 RBAC | 更细的运营角色、审计和连接器治理 |
| 分类 | 新增、编辑、停用、Chat 浏览 | 按租户隔离，停用阻断新执行并保留历史 | 排序、统计和运营筛选 |
| Tool Skill | TOOL 创建、编辑、校验、首次发布 | 版本、差异、回滚新版本、归档 | 导入草稿、脱敏导出、完整治理 |
| Operation | 固定 `customer_report_search` Demo Handler；不提供 Connector 绑定 | 绑定服务端预注册 `knowledge-base.search` fake Operation；契约、超时、取消 | 多 Operation、连接健康、熔断和生产连接 |
| Chat | 分类浏览、手动选择、结构化表单、点击执行、结果卡片 | 登录后按租户/权限显示，进度、取消、终态、产物下载 | 收藏、显示名称、默认参数、排序、重试和限流提示 |
| 用户个性化 | 不保存用户个性化数据；只显示 Schema 默认值 | 不提供 `SkillPreset` | 私有 `SkillPreset`：收藏、显示名称、默认参数、排序 |
| 安全 | local demo flag、loopback、请求字段白名单、固定 Handler | 登录/租户/RBAC、审计 fail closed、二次下载鉴权 | 包扫描、SSRF/SQL/资源耗尽全量测试 |
| 自动化 | `test_m1...` + Playwright m1 | `test_m2...` + Playwright m1/m2 | `test_m3...` + 全量安全/E2E |
| 人工操作 | 10 步 M1 脚本 | 10 步 M2 脚本 | 10 步 M3 脚本 |
| 退出门槛 | 仅可重复本地演示，不能部署共享环境 | 可登录、可隔离、可授权、可取消、可审计、可下载 | 可个性化、可导入、可扩展、可上线治理 |

## Milestone-to-Task Mapping

| 现有任务 | M1：本地 Demo 闭环 | M2：基础安全与受控执行 | M3：个性化/生产治理 |
|---|---|---|---|
| Task 1 合同与 fixture | 受限 Tool Schema、运行请求、M1 fixture | 增加登录/租户/版本/取消/产物字段校验 | 增加导入元数据、Preset 和多 Operation 契约校验 |
| Task 2 持久化 | 分类、Skill、草稿/发布指针、执行和最小事件；可预建未来表但不启用 | 真实租户/角色 grant、Connector/Operation、版本、审计和产物约束 | Preset、导入历史、健康和保留清理字段 |
| Task 3 权限种子 | 不实现真实权限；只实现 local demo identity/gate 所需测试夹具 | 基础登录配套的权限种子、`SKILL_READ`/`SKILL_EXECUTE`、角色 grant CRUD 和授权审计 | 高权限 Connector/导入/审计运营角色 |
| Task 4 Connector | 不实现 Connector registry；固定 Demo Handler 在执行层内置 | 预注册 `knowledge-base.search` fake Operation、Skill 绑定、契约、超时/取消/产物能力 | Connector CRUD、健康检查、readonly DB/registered HTTP/file/ticketing |
| Task 5 管理域 | 分类 CRUD、Skill CRUD、草稿、校验、首次发布；local demo gate | 登录/租户/RBAC、版本历史、差异、角色授权、停用/归档/回滚 | 导入映射、健康状态、运行统计和高级生命周期 |
| Task 6 包导入导出 | 不执行；只保留 schema/feature flag | 不开放页面和路由 | ZIP 预检、冲突处理、导入草稿、脱敏导出 |
| Task 7 SkillPreset | 不实现 | 不实现 | 收藏、显示名称、排序、默认参数、版本失效和私有隔离 |
| Task 8 执行引擎 | Inline Demo driver、短任务、最小事件、结果脱敏 | Celery、状态机、超时、取消、审计、产物、幂等和权限/租户快照 | 重试、配额、限流、熔断、清理和性能治理 |
| Task 9 Chat 后端/SSE | local demo 可用列表、手动执行、快速 SSE/查询结果 | 登录、租户、`SKILL_READ`/`SKILL_EXECUTE`、长任务 SSE、进度、取消、终态和产物事件 | Preset 合并、重试/限流/健康提示和运行指标 |
| Task 10 管理列表/分类 UI | Skills 列表、分类管理、M1 local demo 入口 | 登录态、租户上下文、版本/授权/审计入口和生命周期动作 | Preset 运营、导入/连接器/统计/高级筛选 |
| Task 11 Tool Skill 编辑器 | 基本信息、固定 Demo Handler 提示、Schema、校验、发布 | fake Operation 选择、版本差异、角色授权、回滚/停用/归档确认 | 导入映射、安全报告和连接健康提示 |
| Task 12 管理扩展 UI | 不开放导入/Connector/审计页面 | 审计列表、产物/生命周期相关管理和 Operation 绑定 | 导入导出、Connector、健康、审计高级查询和 Preset 统计 |
| Task 13 Chat UI | 分类浏览、手动选择、表单、执行、结果卡；无个性化控件 | 登录后权限过滤、进度、取消、超时、错误、产物下载 | 收藏、显示名称、默认参数、排序、重试、限流和响应式体验 |
| Task 14 集成发布 | M1 acceptance matrix 和 local demo 浏览器脚本 | M2 登录/租户/RBAC/Connector/长任务/审计/产物验收 | 全量安全、Preset、性能、运行手册和 M3 发布 |

## 里程碑实施顺序和分支策略

1. **M1 实施顺序：** Task 1 → Task 2 → Task 5（management slice）→ Task 8（inline-demo slice）→ Task 9（Chat backend slice）→ Task 10/11（无 Operation 绑定）→ Task 13（无 Preset 的 Chat UI slice）→ Task 14（M1 gate）。Task 3、Task 4、Task 7 的真实能力不得提前进入 M1。
2. **M2 实施顺序：** 以 M1 发布标签为基线，先完成 Task 3 的登录/权限种子和 Task 5/9 的租户/RBAC，再完成 Task 4 的 fake Connector Operation 与 Task 11 的绑定 UI；随后完成 Task 5 的版本生命周期、Task 8 的 Celery/状态机、Task 9 的 SSE、Task 10/12 的治理页面、Task 13 的运行卡，最后 Task 14 M2 gate。任何 M2 任务都必须先验证 M1 的闭环仍然通过。
3. **M3 实施顺序：** 以 M2 发布标签为基线，先完成 Task 7/13 的私有 Preset（收藏、默认参数、显示名称、排序），再完成 Task 6 的 ZIP 安全导入导出和 Task 4/12 的 Connector 管理、多 Operation，接着完成 Task 8/9 的运行治理，最后 Task 13/14 的体验、监控、运行手册和全量安全验收。
4. **分支与回滚：** 每个里程碑从上一个发布标签创建 `codex/tool-skills-m1`、`codex/tool-skills-m2`、`codex/tool-skills-m3` 分支；M1 只在本地运行，M2 起才在 staging 执行同一套登录、迁移和验收命令。若 M2/M3 开关关闭，已发布 Skill 的服务端能力必须按阶段返回明确的 `FEATURE_DISABLED`，不能回退到未认证或未隔离执行；若迁移回滚失败，停止发布，不执行手工删表或跨版本强制修改。
5. **完成标准：** 里程碑完成不是“代码合并”而是对应退出条件、自动化 suite、人工脚本、迁移验证和安全负向测试全部有结果。任何一项缺失都保持当前里程碑状态，不进入下一个里程碑。
## File Structure

### 后端新增文件

| Path | Responsibility |
|---|---|
| server/app/models/skill.py | SkillCategory、Skill、SkillVersion、SkillRoleGrant、SkillPreset、SkillPackageImport ORM 模型。 |
| server/app/models/connector.py | Connector、ConnectorOperation、ConnectorConnection ORM 模型。 |
| server/app/models/skill_execution.py | SkillExecution、SkillExecutionEvent、SkillArtifact ORM 模型。 |
| server/app/schemas/skill.py | 分类、Skill、版本、授权、可用定义、Preset 的请求/响应模型。 |
| server/app/schemas/connector.py | Connector、Operation、连接配置和健康检查 schema。 |
| server/app/schemas/skill_import.py | 导入预检、冲突处理、映射和导出响应 schema。 |
| server/app/schemas/skill_execution.py | 执行创建、状态、结果、取消、重试和 SSE 载荷 schema。 |
| server/app/repositories/skill_repo.py | 分类、Skill、版本、RoleGrant、可用 Skill 查询。 |
| server/app/repositories/connector_repo.py | Connector/Operation/租户连接查询和更新。 |
| server/app/repositories/skill_execution_repo.py | 执行、事件、产物的事务查询和状态更新。 |
| server/app/repositories/skill_preset_repo.py | 用户私有收藏和默认参数的读写。 |
| server/app/services/skill_service.py | 分类、Skill CRUD、版本生命周期、发布前业务校验。 |
| server/app/services/skill_package_service.py | SKILL.md 解析、ZIP 安全预检、导入映射、导出脱敏。 |
| server/app/services/skill_preset_service.py | Preset 权限、引用当前发布版本和默认参数校验。 |
| server/app/services/skill_execution_service.py | 创建执行、授权校验、状态转换、事件写入、结果脱敏和重试。 |
| server/app/services/skill_artifact_service.py | 产物白名单存储、二次鉴权和短时下载令牌。 |
| server/app/integrations/skills/protocols.py | Connector Operation 和执行上下文的统一服务端契约。 |
| server/app/integrations/skills/registry.py | 代码注册的 Operation Registry；不提供用户动态注册接口。 |
| server/app/integrations/skills/operations/knowledge_base.py | 知识库受控检索 Operation。 |
| server/app/integrations/skills/operations/database_readonly.py | 预审核参数化只读查询 Operation。 |
| server/app/integrations/skills/operations/internal_http.py | 固定服务/路径模板的内部 HTTP Operation。 |
| server/app/integrations/skills/operations/file_processing.py | 受限文件处理和产物生成 Operation。 |
| server/app/integrations/skills/operations/ticketing.py | 预配置工单查询/创建/更新 Operation。 |
| server/app/integrations/skills/artifacts.py | 本地/对象存储抽象和安全文件名处理。 |
| server/app/tasks/skill_tasks.py | Celery Skill 执行任务、超时、取消和失败收敛。 |
| server/app/api/v1/skill_categories.py | 分类管理与用户可用分类 API。 |
| server/app/api/v1/skills.py | 管理侧和用户侧 Skill、版本、Preset API。 |
| server/app/api/v1/skill_imports.py | 导入预检、应用、导出 API。 |
| server/app/api/v1/skill_connectors.py | 高权限连接配置、Operation 清单和健康检查 API。 |
| server/app/api/v1/skill_executions.py | 执行详情、取消、重试、产物下载 API。 |
| server/app/db/migrations/versions/0009_tool_skills.py | Skill、Connector、执行和导入相关表及索引。 |
| server/app/db/migrations/versions/0010_skill_chat_links.py | Chat 消息类型、SkillExecution 关联和 Skill 结果元数据字段。 |
| server/tests/test_skill_models.py | ORM、约束、迁移和版本不变量。 |
| server/tests/test_skill_permissions.py | 权限种子、既有租户升级和 RBAC 矩阵。 |
| server/tests/test_skill_connectors.py | Registry、Operation 契约和连接凭据隔离。 |
| server/tests/test_skills_api.py | 分类、Skill CRUD、版本生命周期和角色授权。 |
| server/tests/test_skill_import.py | Agent Skills 包解析、恶意包拒绝和安全导出。 |
| server/tests/test_skill_preset.py | 收藏、默认参数和用户不得创建共享 Skill。 |
| server/tests/test_skill_operations.py | 首批 Connector Operation 的输入边界和权限上下文。 |
| server/tests/test_skill_execution.py | 执行状态机、校验、审计、取消、超时、脱敏和重试。 |
| server/tests/test_skill_sse.py | Skill SSE 事件顺序、心跳、断线恢复和终态。 |
| server/tests/security/test_skill_security.py | ZIP、SSRF、SQL、越权、敏感输出和资源耗尽安全测试。 |
| server/tests/e2e/test_tool_skill_e2e.py | 管理员发布到 Chat 用户执行的完整链路。 |

### 前端新增文件

| Path | Responsibility |
|---|---|
| web/admin/src/features/skills/types.ts | Skill、版本、分类、Connector、Preset、执行类型。 |
| web/admin/src/features/skills/api/skillApi.ts | Skill/版本/可用定义/Preset API。 |
| web/admin/src/features/skills/api/categoryApi.ts | 分类 CRUD 与排序 API。 |
| web/admin/src/features/skills/api/connectorApi.ts | Operation 清单、连接配置、健康检查 API。 |
| web/admin/src/features/skills/api/importApi.ts | 包上传、预检、映射、应用、导出 API。 |
| web/admin/src/features/skills/api/auditApi.ts | Skill 审计查询 API。 |
| web/admin/src/features/skills/pages/SkillPage.tsx | 管理后台 Skill 列表和筛选。 |
| web/admin/src/features/skills/pages/SkillCategoriesPage.tsx | 分类管理。 |
| web/admin/src/features/skills/pages/SkillEditorPage.tsx | 创建/编辑/版本/发布工作区。 |
| web/admin/src/features/skills/pages/SkillImportPage.tsx | 导入预检、冲突和 Operation 映射。 |
| web/admin/src/features/skills/pages/SkillConnectorsPage.tsx | 连接配置和健康状态。 |
| web/admin/src/features/skills/pages/SkillAuditPage.tsx | 导入、发布、授权和执行审计。 |
| web/admin/src/features/skills/components/SkillList.tsx | 列表、状态和操作菜单。 |
| web/admin/src/features/skills/components/SkillCategoryPanel.tsx | 分类 CRUD、排序和停用确认。 |
| web/admin/src/features/skills/components/SkillForm.tsx | Skill 基本资料表单。 |
| web/admin/src/features/skills/components/OperationSelector.tsx | 受控 Operation 选择与契约只读展示。 |
| web/admin/src/features/skills/components/InputSchemaEditor.tsx | 参数字段构建、JSON Schema 预览和校验。 |
| web/admin/src/features/skills/components/PresentationPolicyPanel.tsx | 表单展示、结果展示和执行策略。 |
| web/admin/src/features/skills/components/SkillRoleGrantPanel.tsx | 角色授权。 |
| web/admin/src/features/skills/components/SkillVersionPanel.tsx | 版本差异、验证、测试、发布、回滚。 |
| web/admin/src/features/skills/components/SkillImportPreview.tsx | 包扫描报告、候选映射和冲突处理。 |
| web/admin/src/features/skills/components/SkillExecutionPanel.tsx | 管理员测试运行结果和事件状态。 |
| web/admin/src/features/skills/hooks/useSkillQueries.ts | TanStack Query 查询和失效策略。 |
| web/admin/src/features/skills/hooks/useSkillMutations.ts | 创建、发布、导入和连接配置 mutation。 |
| web/admin/src/features/skills/utils/skillFormValidation.ts | 前端表单约束和安全字段过滤。 |
| web/admin/src/features/skills/utils/skillFormValidation.test.ts | 前端 schema/policy/安全字段单元测试。 |
| web/admin/src/features/chat/api/skillApi.ts | Chat 侧可用 Skill、Preset 和执行请求。 |
| web/admin/src/features/chat/hooks/useSkillStream.ts | Skill SSE 解析、取消、重试和终态同步。 |
| web/admin/src/features/chat/components/SkillDrawer.tsx | 分类、收藏和可用 Skill 列表。 |
| web/admin/src/features/chat/components/SkillDetailPanel.tsx | Skill 说明、限制、副作用和执行入口。 |
| web/admin/src/features/chat/components/SkillInputForm.tsx | 按受限 JSON Schema 渲染参数表单。 |
| web/admin/src/features/chat/components/SkillRunCard.tsx | 请求、状态、结果、错误、产物和操作按钮。 |
| web/admin/src/styles/skills.css | 管理后台和 Chat Skill UI 样式、响应式规则。 |

### 现有文件修改

| Path | Change |
|---|---|
| server/app/db/base.py | 导入新 ORM 模型，确保 Base.metadata 注册。 |
| server/app/services/seed_service.py | 增加 Skill 权限并让既有租户幂等补齐权限和角色关联。 |
| server/app/api/v1/__init__.py | 注册五个 Skill API router。 |
| server/app/models/chat.py | 增加消息类型、SkillExecution 关联和安全元数据。 |
| server/app/schemas/chat.py | 返回 Skill 消息字段，新增 Skill 请求 schema。 |
| server/app/repositories/chat_repo.py | 保存和读取 Skill 请求/结果消息。 |
| server/app/api/v1/chat.py | 增加 POST /chat/sessions/{session_id}/skill-runs 流式入口。 |
| server/app/services/chat_service.py | 保持普通 Chat 与 Skill 执行边界，复用会话权限和 SSE。 |
| server/app/services/sse_service.py | 复用心跳机制并支持 Skill 事件序列。 |
| server/app/tasks/celery_app.py | 加载 Skill Celery task。 |
| server/app/core/config.py | 增加 Skill 导入、执行、产物、队列和下载令牌配置。 |
| requirements.txt | 增加 PyYAML 和 jsonschema。 |
| pyproject.toml | 注册 `m1`、`m2`、`m3` pytest markers，使后端和 Playwright 验收可以按里程碑独立运行。 |
| web/admin/src/routes/index.tsx | 增加 Skills 管理后台路由和权限门禁。 |
| web/admin/src/api/queryClient.ts | 增加 Skill 相关 query key。 |
| web/admin/src/features/chat/pages/ChatPage.tsx | 增加 Skill 抽屉、运行卡和刷新逻辑。 |
| web/admin/src/features/chat/types.ts | 增加 Skill 消息和执行类型。 |
| web/admin/src/features/chat/api/chatApi.ts | 保持普通消息 API，并导出 Skill stream 调用。 |
| web/admin/src/styles/index.css | 引入 skills.css。 |
| web/admin/package.json | 增加前端纯函数测试命令和 Vitest。 |

---


## File structure addendum and implementation conventions

The implementation must keep the existing module boundaries and add only the following supporting files where the responsibility cannot be kept in an existing module:

| Path | Responsibility |
|---|---|
| `server/app/services/skill_schema_service.py` | Normalize and validate the supported Tool Skill input-schema subset, presentation rules, execution-policy ceilings, and import metadata. |
| `server/app/services/skill_audit_service.py` | Write redacted management/import/execution audit events and expose a read-only query facade. |
| `server/app/services/connector_service.py` | Tenant connection configuration, encrypted secret references, health checks, and fail-closed availability checks. |
| `server/tests/fixtures/skills/customer-report-export/SKILL.md` | Valid Agent Skills fixture used by import, export, and e2e tests. |
| `server/tests/fixtures/skills/customer-report-export/references/INPUTS.md` | Non-executable reference file proving allowed package resources survive a round trip. |
| `server/tests/fixtures/skills/malicious/` | Test-only packages containing scripts, symlinks, traversal entries, secrets, and oversized members. |
| `web/admin/src/features/skills/components/SchemaFieldRow.tsx` | One editable field row used by the administrator schema builder. |
| `web/admin/src/features/skills/components/ValidationSummary.tsx` | Blocking errors and non-blocking warnings returned by server validation. |
| `web/admin/src/features/skills/components/ConfirmActionDialog.tsx` | Explicit confirmation for publish, disable, archive, rollback, and side-effect test runs. |
| `web/admin/src/features/skills/components/SkillEditorSteps.tsx` | Step navigation, completion indicators, and draft dirty-state guard. |
| `web/admin/src/features/skills/utils/skillPackagePreview.ts` | Safe client-side preview helpers; never parses or executes package scripts. |
| `web/admin/tests/t20_tool_skill_admin_playwright.py` | Browser acceptance tests for the complete administrator workflow. |
| `web/admin/tests/t21_tool_skill_chat_playwright.py` | Browser acceptance tests for manual Chat execution and result cards. |
| `server/tests/e2e/test_m1_tool_skill_closed_loop.py` | M1 服务端端到端闭环：管理员创建/发布、Demo 用户浏览/执行和 local-demo 安全负向请求。 |
| `server/tests/e2e/test_m2_tool_skill_operational_loop.py` | M2 服务端端到端闭环：版本、RBAC、生命周期、异步执行、审计、取消和产物下载。 |
| `server/tests/e2e/test_m3_tool_skill_complete.py` | M3 服务端端到端闭环：导入/导出、Connector 健康、多 Operation、限流和生产治理。 |

All new API responses use the existing Pydantic alias convention (`snake_case` internally, `camelCase` over HTTP). All management mutations must return the updated resource plus a request ID. All security decisions are server-side; client-side filtering is only a usability optimization.

## Detailed implementation plan

### Task 1: Freeze the Tool Skill contract and test fixtures

**Files:**
- Create: `server/app/schemas/skill.py`
- Create: `server/app/schemas/connector.py`
- Create: `server/app/schemas/skill_import.py`
- Create: `server/app/schemas/skill_execution.py`
- Create: `server/tests/fixtures/skills/customer-report-export/SKILL.md`
- Create: `server/tests/fixtures/skills/customer-report-export/references/INPUTS.md`
- Create: `server/tests/test_skill_contracts.py`
- Modify: `server/requirements.txt`

- [ ] **Step 1: Write the failing contract tests.**

  Add tests that make the public contract executable before any ORM or route implementation exists:

  ```python
  def test_skill_md_frontmatter_contract():
      package = Path("server/tests/fixtures/skills/customer-report-export")
      document = (package / "SKILL.md").read_text(encoding="utf-8")
      parsed = SkillPackageManifest.parse_skill_md(
          skill_dir_name="customer-report-export", document=document
      )
      assert parsed.name == "customer-report-export"
      assert parsed.description
      assert parsed.metadata["lingxi"]["operation_key"] == "export_customer_report"

  def test_skill_run_request_rejects_client_control_fields():
      with pytest.raises(ValidationError):
          SkillRunCreateRequest.model_validate(
              {
                  "skillId": "s1",
                  "input": {},
                  "skillVersionId": "v1",
                  "connectorKey": "reporting",
              }
          )

  def test_input_schema_rejects_credential_and_network_control_fields():
      with pytest.raises(ValueError, match="forbidden input field"):
          ToolInputSchema.model_validate(
              {"type": "object", "properties": {"password": {"type": "string"}}}
          )
  ```

  Add cases for an invalid uppercase name, leading/trailing hyphen, consecutive hyphen, missing description, description over 1024 characters, non-object root schema, `additionalProperties: true`, `sql`, `url`, `headers`, and `credential` fields. The server contract must reject these before a database write.

- [ ] **Step 2: Run the focused tests and confirm they fail for missing schemas.**

  Run from `D:\codeproject\python\lingxi`:

  ```powershell
  pytest server/tests/test_skill_contracts.py -q
  ```

  Expected: FAIL with import errors for the new schema classes. No route or database test should be needed to expose a contract failure.

- [ ] **Step 3: Define the exact request/response schemas.**

  Implement the following models, keeping the wire fields camelCase through aliases:

  ```python
  class SkillRunCreateRequest(BaseModel):
      model_config = ConfigDict(populate_by_name=True, extra="forbid")
      skill_id: str = Field(alias="skillId", min_length=1, max_length=80)
      input: dict[str, Any] = Field(default_factory=dict)

  class SkillVersionDraftRequest(BaseModel):
      model_config = ConfigDict(populate_by_name=True, extra="forbid")
      manifest: SkillPackageManifest
      input_schema: ToolInputSchema = Field(alias="inputSchema")
      presentation_config: PresentationConfig = Field(alias="presentationConfig")
      execution_policy: ExecutionPolicy = Field(alias="executionPolicy")
      connector_operation_id: str = Field(alias="connectorOperationId", min_length=1)
      role_ids: list[str] = Field(default_factory=list, alias="roleIds")

  class SkillAvailableDefinition(BaseModel):
      id: str
      key: str
      name: str
      description: str
      category: SkillCategorySummary
      version: int
      input_schema: dict[str, Any] = Field(alias="inputSchema")
      presentation_config: dict[str, Any] = Field(alias="presentationConfig")
      execution_policy: dict[str, Any] = Field(alias="executionPolicy")
      is_favorite: bool = Field(alias="isFavorite")
      default_input: dict[str, Any] = Field(alias="defaultInput")
  ```

  `SkillPackageManifest` must parse required `name` and `description`, optional `license`, `compatibility`, `metadata`, and the markdown body. It must enforce the Agent Skills name rules, including matching the root directory name and rejecting consecutive hyphens. The platform may store `metadata.lingxi` only as a candidate mapping; it never grants roles or access from package metadata.

  The supported first-phase input-schema subset is a root object with named properties, `required`, and `additionalProperties: false`. Property types are `string`, `integer`, `number`, `boolean`, `array`, and a platform file reference. `enum`, `format`, `minLength`, `maxLength`, `minimum`, `maximum`, `items`, and `description` are allowed only within configured limits. Reject property names and descriptions that attempt to introduce `password`, `secret`, `token`, `credential`, `authorization`, `headers`, `url`, `sql`, or equivalent controls. The actual connector contract remains authoritative.

- [ ] **Step 4: Add the fixture and dependencies, then rerun the tests.**

  The fixture must contain exactly one frontmatter block and a body with purpose, input, output, limits, and examples. Add `PyYAML` and `jsonschema` to `server/requirements.txt`. Run:

  ```powershell
  pytest server/tests/test_skill_contracts.py -q
  ```

  Expected: PASS, with all malicious schema cases rejected and the valid fixture parsed into normalized data.

- [ ] **Step 5: Commit the contract slice.**

  ```powershell
  git add server/app/schemas server/tests/fixtures/skills server/tests/test_skill_contracts.py server/requirements.txt
  git commit -m "feat: define tool skill contracts"
  ```

### Task 2: Add Skill, Connector, execution, and import persistence

**Files:**
- Create: `server/app/models/skill.py`
- Create: `server/app/models/connector.py`
- Create: `server/app/models/skill_execution.py`
- Create: `server/app/db/migrations/versions/0009_tool_skills.py`
- Modify: `server/app/db/base.py`
- Create: `server/tests/test_skill_models.py`

- [ ] **Step 1: Write failing model and migration tests.**

  Cover phase boundaries, uniqueness, lifecycle fields, and version immutability. M1 uses one local demo namespace; tenant/role/preset isolation tests are marked m2 or m3 and must not be used to claim M1 security:

  ```python
  def test_skill_key_is_unique_per_tenant(db, tenant_a, tenant_b):
      create_skill(db, tenant_a, key="customer-report-export")
      create_skill(db, tenant_b, key="customer-report-export")
      with pytest.raises(IntegrityError):
          create_skill(db, tenant_a, key="customer-report-export")

  @pytest.mark.m2
  def test_grant_and_execution_snapshot_are_tenant_scoped(db):
      assert SkillPreset.__table__.c.user_id is not None
      assert SkillRoleGrant.__table__.c.role_id is not None
      assert SkillExecution.__table__.c.requested_role_snapshot is not None

  def test_migration_upgrade_and_downgrade_are_sqlite_safe(migration_engine):
      command.upgrade(migration_engine, "head")
      assert {"skills", "skill_versions", "skill_executions"}.issubset(
          inspect(migration_engine).get_table_names()
      )
      command.downgrade(migration_engine, "0008_qa_split_long_running")
  ```

  Add a test that an already published version cannot be mutated through the service layer and that a new edit creates a new draft version instead.

- [ ] **Step 2: Run the tests to verify the tables and model imports are absent.**

  ```powershell
  pytest server/tests/test_skill_models.py -q
  ```

  Expected: FAIL because the new model modules and revision do not exist.

- [ ] **Step 3: Implement the ORM entities and Base registration.**

  Use the existing `IdMixin`, `TimestampMixin`, `tenant_id` convention, and string status values for SQLite/PostgreSQL compatibility. Add these fields:

  - `SkillCategory`: `tenant_id`, `key`, `name`, `description`, `icon`, `display_order`, `status`, timestamps; unique `(tenant_id, key)`.
  - `Skill`: `tenant_id`, `category_id`, `key`, `name`, `description`, `icon`, `skill_type`, `status`, `current_published_version_id`, `created_by_user_id`, `optimistic_lock`; unique `(tenant_id, key)`.
  - `SkillVersion`: `skill_id`, `version_number`, `package_manifest`, `input_schema`, `presentation_config`, `execution_policy`, `connector_operation_id`, `demo_handler_key`, `status`, `created_by_user_id`, `published_at`, `published_by_user_id`, `content_hash`; unique `(skill_id, version_number)`. M1 fills only the fixed `demo_handler_key`; M2 fills `connector_operation_id` after server-side registry resolution.
  - `SkillRoleGrant`: `skill_version_id`, `role_id`, `can_execute`; unique `(skill_version_id, role_id)`. Table/service are M2-only.
  - `SkillPreset`: `tenant_id`, `user_id`, `skill_id`, `display_name`, `is_favorite`, `default_input`, `display_order`; unique `(user_id, skill_id)` and no role/connector fields. Table/API are M3-only.
  - `Connector`: platform key, name, type, status, connector version, health status, timestamps. Registry/connection behavior is M2/M3-only.
  - `ConnectorOperation`: connector ID, key, display name, input/output contracts, side-effect level, timeout ceiling, allowed tenant config, status; unique `(connector_id, key)`. Binding is M2-only.
  - `ConnectorConnection`: tenant ID, connector ID, safe display name, encrypted secret reference, non-secret config, status, last health check; unique `(tenant_id, connector_id)`. Tenant connection enforcement is M2-only.
  - `SkillExecution`: tenant/skill/version/session/message references, requester, role snapshot, status, timestamps, duration, request ID, operation snapshot, redacted input/result, safe error fields, retry/cancel references. M1 uses a fixed local namespace; M2 starts populating authenticated tenant/role snapshots.
  - `SkillExecutionEvent`: execution ID, sequence, event name, safe payload, created timestamp; unique `(execution_id, sequence)`.
  - `SkillArtifact`: execution ID, storage key, safe filename, MIME, size, checksum, expiry, classification, download policy. M2-only for user downloads.
  - `SkillPackageImport`: tenant/uploader, safe filename, package hash, manifest summary, status, validation report, conflict resolution, created skill/version references. M3-only.

  Register all new model modules as plain imports in `server/app/db/base.py`, matching the repository's circular-import-safe pattern.

- [ ] **Step 4: Create `0009_tool_skills.py` with indexes and safe downgrade.**

  Create the tables in dependency order, add foreign keys and indexes for `(tenant_id, status)`, `(skill_id, status)`, `(execution_id, sequence)`, and `(tenant_id, key)`. Add a foreign key from `skills.current_published_version_id` after `skill_versions` exists. Enforce the “at most one published version” invariant in the service transaction; on PostgreSQL also add a partial unique index for published versions if the database supports it. The migration must not store plaintext credentials.

  The downgrade must drop the partial index first, then artifact/events/executions, package imports, presets/grants/versions, connector tables, and skills/categories in reverse dependency order. It must work against the existing SQLite test engine.

- [ ] **Step 5: Run migration and model tests.**

  ```powershell
  pytest server/tests/test_skill_models.py -q
  alembic -c server/alembic.ini upgrade head
  ```

  Expected: PASS; the schema reaches head without altering unrelated tables, and the downgrade test returns to revision `0008_qa_split_long_running`.

- [ ] **Step 6: Commit persistence.**

  ```powershell
  git add server/app/models server/app/db/base.py server/app/db/migrations/versions/0009_tool_skills.py server/tests/test_skill_models.py
  git commit -m "feat: persist tool skills and executions"
  ```

### Task 3: Add Skill permissions and idempotent seed upgrades (M2)

**Files:**
- Modify: `server/app/services/seed_service.py`
- Create: `server/tests/test_skill_permissions.py`

- [ ] **Step 1: Write failing permission tests.**

  Verify fresh seed data and upgrade behavior for existing tenants:

  ```python
  def test_system_admin_receives_all_skill_management_permissions(seed_snapshot):
      assert {
          "SKILL_READ", "SKILL_EXECUTE", "SKILL_MANAGE",
          "SKILL_CATEGORY_MANAGE", "SKILL_CONNECTOR_MANAGE", "SKILL_AUDIT_READ",
      }.issubset(seed_snapshot.roles["system_admin"].permissions)

  def test_employee_can_read_and_execute_but_cannot_manage(seed_snapshot):
      permissions = seed_snapshot.roles["employee"].permissions
      assert {"SKILL_READ", "SKILL_EXECUTE"}.issubset(permissions)
      assert "SKILL_MANAGE" not in permissions

  def test_rerunning_seed_does_not_duplicate_permissions_or_role_links(db):
      first = seed_identity_data(db)
      second = seed_identity_data(db)
      assert count_permissions(db, "SKILL_READ") == 1
      assert count_role_permission_links(db, first.roles["system_admin"].id, "SKILL_MANAGE") == 1
  ```

- [ ] **Step 2: Run the tests and observe missing permission codes.**

  ```powershell
  pytest server/tests/test_skill_permissions.py -q
  ```

  Expected: FAIL because the six Skill permission codes are not in the current seed map and the existing seed path is not yet upgraded for them.

- [ ] **Step 3: Add the permission matrix.**

  Add exactly these codes to `SYSTEM_PERMISSIONS` and `ROLE_PERMISSION_MAP`:

  | Role | New permissions |
  |---|---|
  | `SYSTEM_ADMIN` | all six codes |
  | `KNOWLEDGE_ADMIN` | `SKILL_READ`, `SKILL_EXECUTE` |
  | `EMPLOYEE` | `SKILL_READ`, `SKILL_EXECUTE` |

  Keep `SKILL_CONNECTOR_MANAGE` restricted to `SYSTEM_ADMIN`. Make the seed lookup create missing permissions, append missing role links, and never delete manually added permissions. Existing tenants must receive the same upgrade when the seed service runs again.

- [ ] **Step 4: Run the focused and existing RBAC tests.**

  ```powershell
  pytest server/tests/test_skill_permissions.py server/tests/test_auth_rbac.py -q
  ```

  Expected: PASS, with no duplicate rows and no regression in existing permission checks. These tests are the M2 gate for real login/tenant context and `SKILL_READ` / `SKILL_EXECUTE`; they must not be included in the M1 success claim.

- [ ] **Step 5: Commit the permission slice.**

  ```powershell
  git add server/app/services/seed_service.py server/tests/test_skill_permissions.py
  git commit -m "feat: seed tool skill permissions"
  ```

### Task 4: Register controlled Connector Operations and tenant connections (M2/M3)

**Files:**
- Create: `server/app/integrations/skills/protocols.py`
- Create: `server/app/integrations/skills/registry.py`
- Create: `server/app/integrations/skills/operations/knowledge_base.py`
- Create: `server/app/integrations/skills/operations/database_readonly.py`
- Create: `server/app/integrations/skills/operations/internal_http.py`
- Create: `server/app/integrations/skills/operations/file_processing.py`
- Create: `server/app/integrations/skills/operations/ticketing.py`
- Create: `server/app/services/connector_service.py`
- Create: `server/app/repositories/connector_repo.py`
- Create: `server/app/api/v1/skill_connectors.py`
- Modify: `server/app/models/connector.py`
- Modify: `server/app/core/config.py`
- Create: `server/tests/test_skill_connectors.py`
- Create: `server/tests/test_skill_operations.py`

- [ ] **Step 1: Write failing registry and security tests.**

  The tests must prove that the registry is static and that no client value can select an arbitrary connector:

  ```python
  def test_registry_contains_only_approved_operations():
      keys = set(operation_registry.keys())
      assert keys == {
          "knowledge-base.search",
          "database-readonly.run-template",
          "internal-http.call-registered",
          "file-processing.transform",
          "ticketing.search",
          "ticketing.create",
          "ticketing.update",
      }

  def test_registry_does_not_accept_runtime_operation_registration():
      with pytest.raises(AttributeError):
          operation_registry.register_from_request({"key": "shell.exec"})

  def test_internal_http_uses_registered_target_not_payload_url():
      operation = operation_registry.get("internal-http.call-registered")
      with pytest.raises(ConnectorInputError, match="url"):
          operation.validate_input({"url": "http://169.254.169.254/latest/meta-data"})

  def test_database_operation_rejects_sql_text():
      operation = operation_registry.get("database-readonly.run-template")
      with pytest.raises(ConnectorInputError, match="template"):
          operation.validate_input({"sql": "drop table users"})
  ```

- [ ] **Step 2: Run the tests and confirm the registry and protocol are absent.**

  ```powershell
  pytest server/tests/test_skill_connectors.py server/tests/test_skill_operations.py -q
  ```

  Expected: FAIL with missing module/registry errors.

- [ ] **Step 3: Implement the operation protocol and immutable registry.**

  Define the protocol exactly as the design contract requires:

  ```python
  class SkillOperation(Protocol):
      key: str
      input_schema: dict[str, Any]
      output_schema: dict[str, Any]
      side_effect_level: Literal["READ_ONLY", "EXTERNAL_WRITE", "FILE_WRITE"]

      def validate_availability(self, context: SkillExecutionContext) -> None: ...
      def execute(self, context: SkillExecutionContext, payload: dict[str, Any]) -> SkillOperationResult: ...
      def cancel(self, context: SkillExecutionContext) -> None: ...
  ```

  `SkillExecutionContext` contains tenant ID, user ID, role IDs/codes snapshot, request ID, cancellation event, redacted logger, connector connection, and artifact writer. `SkillOperationResult` contains safe summary, structured data, progress events, artifacts, and a safe retryable error representation. The registry is assembled from code at process startup and exposes read-only operation metadata to the management API. Skill packages and users cannot register or replace operations.

- [ ] **Step 4: Implement and test each first-phase operation boundary.**

  - `knowledge-base.search` (M2 fake Operation): accept query, optional category/space identifiers, and bounded page size; derive accessible knowledge scope from `AccessContext`, never from an untrusted tenant/user field.
  - `database-readonly.run-template`: accept only a registered `template_key` and typed parameters; require the operation's server-side template to be marked read-only; reject SQL, table names, connection strings, and arbitrary parameter names.
  - `internal-http.call-registered`: accept an operation-specific body/path-template parameter object; resolve host, method, path, and headers from the registered operation; reject URL, host, method, proxy, and raw header inputs; enforce HTTPS/allowlisted service and response-size limits.
  - `file-processing.transform`: accept a platform file reference and a registered transformation; verify the current user can read the source artifact; enforce extension, MIME, size, decompression, and output limits.
  - `ticketing.search/create/update`: accept operation-specific typed fields; attach tenant/user context server-side; require explicit confirmation for `create` and `update`; never accept credential, endpoint, or arbitrary field-map inputs.

  Each operation must call `validate_availability` before work and fail closed when the connector is disabled, unhealthy, missing a tenant connection, or missing a required secret reference.

- [ ] **Step 5: Implement connector service and management endpoints.**

  `ConnectorService` reads connector and operation metadata from the registry, persists only tenant-safe connection configuration, encrypts secret values with the existing `encrypt_secret`, and returns only `hasSecret`, masked display values, and health status. It must never serialize the encrypted value or decrypted value. Add:

  | Method | Path | Rule |
  |---|---|---|
  | `GET` | `/skill-connectors` | `SKILL_CONNECTOR_MANAGE`; registry plus current tenant status. |
  | `GET` | `/skill-connectors/{connector_key}/operations` | `SKILL_CONNECTOR_MANAGE`; read-only operation contracts. |
  | `PUT` | `/skill-connectors/{connector_key}/connection` | `SKILL_CONNECTOR_MANAGE`; safe config and optional secret write. |
  | `POST` | `/skill-connectors/{connector_key}/health-check` | `SKILL_CONNECTOR_MANAGE`; no secret in response. |

  Reject connector keys and operation keys not in the registry, reject unknown config keys, and use a transaction that rolls back the connection update if the health check or audit write fails.

- [ ] **Step 6: Run connector and security tests.**

  ```powershell
  pytest server/tests/test_skill_connectors.py server/tests/test_skill_operations.py server/tests/security/test_secret_redaction.py -q
  ```

  Expected: PASS; the tests must show that a valid registered operation executes with context, while arbitrary URL, SQL, credential, and operation-selection inputs are rejected.

- [ ] **Step 7: Commit the connector slice.**

  ```powershell
  git add server/app/integrations/skills server/app/services/connector_service.py server/app/repositories/connector_repo.py server/app/api/v1/skill_connectors.py server/app/models/connector.py server/app/core/config.py server/tests/test_skill_connectors.py server/tests/test_skill_operations.py
  git commit -m "feat: add controlled skill connector registry"
  ```

### Task 5: Implement categories, Skill CRUD, versions, role grants, and lifecycle APIs (M1/M2)

**Files:**
- Create: `server/app/repositories/skill_repo.py`
- Create: `server/app/services/skill_schema_service.py`
- Create: `server/app/services/skill_service.py`
- Create: `server/app/services/skill_audit_service.py`
- Create: `server/app/api/v1/skill_categories.py`
- Create: `server/app/api/v1/skills.py`
- Modify: `server/app/schemas/skill.py`
- Modify: `server/app/api/v1/__init__.py`
- Create: `server/tests/test_skills_api.py`

- [ ] **Step 1: Write failing service/API tests for the lifecycle.**

  Use milestone-specific fixtures. M1 uses `local_demo_admin`/`local_demo_user` and one local namespace; M2 adds authenticated admin/employee, second tenant, active/inactive category, role and fake Connector fixtures. Cover the matching cases:

  ```python
  def test_admin_creates_tool_skill_draft(client, admin_token, active_category, operation):
      response = client.post(
          "/api/v1/skills",
          headers=admin_token,
          json={
              "key": "customer-report-export",
              "name": "客户报表导出",
              "description": "根据筛选条件导出客户报表。",
              "categoryId": active_category.id,
              "skillType": "TOOL",
          },
      )
      assert response.status_code == 201
      assert response.json()["data"]["status"] == "DRAFT"

  def test_employee_cannot_create_or_edit_system_skill(client, employee_token):
      assert client.post("/api/v1/skills", headers=employee_token, json={}).status_code == 403
      assert client.post("/api/v1/skills/s1/versions", headers=employee_token, json={}).status_code == 403

  def test_published_edit_creates_new_draft_without_mutating_history(...): ...
  def test_publish_requires_operation_active_category_active_and_role_grant(...): ...
  def test_disabled_category_hides_skill_and_blocks_new_execution(...): ...
  def test_archive_is_terminal_and_rollback_publishes_a_new_version(...): ...
  def test_cross_tenant_skill_and_role_ids_are_not_resolvable(...): ...
  ```

  Add API assertions for 400/409 error codes, request IDs, optimistic-lock conflicts, and no disclosure of connector internals in user-facing definitions.

- [ ] **Step 2: Run the tests and confirm no routes/services exist.**

  ```powershell
  pytest server/tests/test_skills_api.py -q
  ```

  Expected: FAIL with 404 for the new endpoints or import errors.

- [ ] **Step 3: Implement category repository/service/router.**

  Add these routes:

  | Method | Path | Permission | Behavior |
  |---|---|---|---|
  | `GET` | `/skill-categories` | `SKILL_CATEGORY_MANAGE` | Tenant admin list, status filter, counts. |
  | `POST` | `/skill-categories` | `SKILL_CATEGORY_MANAGE` | Create active category with tenant-unique key. |
  | `PATCH` | `/skill-categories/{category_id}` | `SKILL_CATEGORY_MANAGE` | Rename, describe, icon/order update. |
  | `POST` | `/skill-categories/{category_id}/disable` | `SKILL_CATEGORY_MANAGE` | Disable without deleting history. |
  | `POST` | `/skill-categories/{category_id}/enable` | `SKILL_CATEGORY_MANAGE` | Re-enable. |
  | `DELETE` | `/skill-categories/{category_id}` | `SKILL_CATEGORY_MANAGE` | Only when no Skill references it. |
  | `GET` | `/skill-categories/available` | `SKILL_READ` | Active categories with only currently executable Skill counts. |

  In M1, repositories are reachable only through the loopback local-demo guard and use the single demo namespace. In M2, every repository query must include `tenant_id == context.tenant_id`, and every route must enforce the current user permission. Category deletion returns a conflict when any Skill exists; disabling does not mutate Skill status.

- [ ] **Step 4: Implement Skill and version service invariants.**

  Add management routes:

  | Method | Path | Permission | Behavior |
  |---|---|---|---|
  | `GET` | `/skills` | `SKILL_MANAGE` | Filter by search, category, status, operation, role; paginate. |
  | `POST` | `/skills` | `SKILL_MANAGE` | Create TOOL-only Skill and initial DRAFT version shell. |
  | `GET` | `/skills/{skill_id}` | `SKILL_MANAGE` | Full admin definition, versions, role grants, validation status. |
  | `PATCH` | `/skills/{skill_id}` | `SKILL_MANAGE` | Update base metadata with optimistic lock. |
  | `POST` | `/skills/{skill_id}/versions` | `SKILL_MANAGE` | Create next immutable DRAFT from current version or supplied draft. |
  | `GET` | `/skills/{skill_id}/versions` | `SKILL_MANAGE` | Version list and lifecycle state. |
  | `GET` | `/skills/{skill_id}/versions/{version_id}/diff` | `SKILL_MANAGE` | Server-generated redacted JSON/markdown diff. |
  | `POST` | `/skills/{skill_id}/versions/{version_id}/validate` | `SKILL_MANAGE` | Return blocking errors and warnings without publishing. |
  | `POST` | `/skills/{skill_id}/versions/{version_id}/publish` | `SKILL_MANAGE` | Transactionally publish exactly one version. |
  | `POST` | `/skills/{skill_id}/disable` | `SKILL_MANAGE` | Stop new executions; keep history. |
  | `POST` | `/skills/{skill_id}/enable` | `SKILL_MANAGE` | Re-enable only if a published version remains valid. |
  | `POST` | `/skills/{skill_id}/archive` | `SKILL_MANAGE` | Terminal archive. |
  | `POST` | `/skills/{skill_id}/versions/{version_id}/rollback` | `SKILL_MANAGE` | Create/publish a new version copied from the selected historical version. |

  A Skill create/edit request accepts `skillType` only when it is `TOOL`; return `SKILL_TYPE_NOT_AVAILABLE` for `PROMPT` in this phase. In M1, publishing requires the fixed `customer_report_search` Demo Handler, an active category, a valid input schema and local-demo gate; it does not require a role grant or Connector Operation. In M2, publishing additionally requires an active Skill, exactly one active pre-registered Connector Operation, policy within operation ceilings, at least one current-tenant role grant, no unresolved import mapping, and a successful audit insert in the same transaction. Publishing moves the old version to `SUPERSEDED`; it never updates a published row in place.

- [ ] **Step 5: Add available-definition and role-grant behavior.**

  Add `GET /skills/available`, `GET /skills/{skill_id}/available-definition`, and, in M2 only, admin role-grant mutations under `/skills/{skill_id}/versions/{version_id}/role-grants`. M1 available queries use the local demo gate and fixed Handler. In M2 the available query must join the current published version, active category, active Connector/Operation, the current user's tenant and roles, and `SKILL_READ`/`SKILL_EXECUTE`; it must return no row for an unauthorized user, even if the user guesses the key or ID. The definition response omits `connector_key`, `operation_key`, internal endpoint, credentials, role IDs, and raw package files.

  Role grant mutation accepts only role IDs belonging to the current tenant. It stores `can_execute=true` in phase one and writes an audit event with added/removed role codes, not secret data.

- [ ] **Step 6: Add validation and audit services.**

  `SkillSchemaService` validates the manifest, schema, presentation config, operation contract, execution policy, sensitive output paths, and package mapping. Return a stable structure:

  ```json
  {
    "valid": false,
    "errors": [
      {"code": "ROLE_REQUIRED", "path": "roleIds", "message": "至少授权一个角色"}
    ],
    "warnings": [
      {"code": "EXTERNAL_WRITE_CONFIRMATION", "path": "executionPolicy", "message": "外部写操作必须开启二次确认"}
    ]
  }
  ```

  `SkillAuditService` writes `SKILL_CREATED`, `SKILL_VERSION_CREATED`, `SKILL_VALIDATED`, `SKILL_PUBLISHED`, `SKILL_DISABLED`, `SKILL_ARCHIVED`, `SKILL_ROLES_CHANGED`, and `SKILL_ROLLED_BACK` with actor, tenant, request ID, resource IDs, before/after summary, and redacted diff. If the audit insert fails, the mutation rolls back.

- [ ] **Step 7: Run API/RBAC tests and commit.**

  ```powershell
  pytest server/tests/test_skills_api.py server/tests/test_skill_permissions.py -q
  ```

  Expected: PASS; administrators can manage only their tenant's Tool Skills, users cannot access management routes, published versions are immutable, and disabled/archived resources are handled exactly as the lifecycle specifies.

  ```powershell
  git add server/app/repositories/skill_repo.py server/app/services/skill_schema_service.py server/app/services/skill_service.py server/app/services/skill_audit_service.py server/app/api/v1/skill_categories.py server/app/api/v1/skills.py server/app/schemas/skill.py server/app/api/v1/__init__.py server/tests/test_skills_api.py
  git commit -m "feat: add tool skill management APIs"
  ```

### Task 6: Implement secure Agent Skills package import, conflict handling, and export

**Files:**
- Create: `server/app/services/skill_package_service.py`
- Create: `server/app/api/v1/skill_imports.py`
- Modify: `server/app/schemas/skill_import.py`
- Modify: `server/app/services/skill_audit_service.py`
- Create: `server/tests/test_skill_import.py`
- Modify: `server/tests/security/test_skill_security.py`

- [ ] **Step 1: Write failing package-security tests.**

  Build ZIP bytes in memory so the tests do not depend on an external archive:

  ```python
  @pytest.mark.parametrize("member", ["skill/scripts/run.py", "skill/../escape.txt", "/absolute.txt", "skill/.env", "skill/bin/tool.exe"])
  def test_import_rejects_dangerous_members(member):
      response = import_service.preview(make_zip({member: b"bad"}), admin_context)
      assert response.status == "REJECTED"
      assert response.validation_report["blocking"]

  def test_import_rejects_symlink_and_zip_bomb(...): ...
  def test_import_rejects_secret_patterns_in_skill_md(...): ...
  def test_import_requires_one_root_and_one_skill_md(...): ...
  def test_import_does_not_execute_scripts(monkeypatch, ...): ...
  def test_same_key_requires_explicit_conflict_choice(...): ...
  def test_export_contains_no_role_secret_input_result_or_internal_endpoint(...): ...
  ```

- [ ] **Step 2: Run the security tests and confirm the importer does not exist.**

  ```powershell
  pytest server/tests/test_skill_import.py server/tests/security/test_skill_security.py -q
  ```

  Expected: FAIL with missing package service or endpoint behavior.

- [ ] **Step 3: Implement ZIP preflight before extraction.**

  `SkillPackageService.preview` must inspect `ZipInfo` entries before writing any file. Enforce configuration values added to `server/app/core/config.py`: maximum compressed bytes, uncompressed bytes, member count, member bytes, nesting depth, and accepted MIME/extensions. Reject:

  - multiple roots, missing or duplicate `SKILL.md`, empty package, duplicate normalized paths;
  - absolute paths, `..` traversal, NUL bytes, Windows drive prefixes, symlinks, hard-link-like entries, and unusual archive types;
  - `scripts/`, `node_modules/`, `.venv/`, `__pycache__/`, `.env`, Python/JS/shell/PowerShell/executable files;
  - encrypted members, compression ratio above the configured limit, unknown binary types, and file contents matching private-key, cloud-key, bearer-token, database-URL, or common secret assignment patterns;
  - oversized markdown/references/assets or unsupported asset MIME types.

  Extract into a server-created temporary directory only after all entry checks pass. Never import an executable module, call a subprocess, evaluate YAML tags, or follow a symlink. Parse only the single `SKILL.md`, allow `references/` and `assets/`, normalize the manifest, calculate a package hash, and generate a redacted validation report.

- [ ] **Step 4: Implement candidate mapping and explicit conflict resolution.**

  `POST /skills/imports` accepts multipart ZIP and returns an import ID plus preview report. `POST /skills/imports/{import_id}/apply` accepts:

  ```json
  {
    "conflictResolution": "CREATE_NEW | NEW_DRAFT_VERSION | CANCEL",
    "targetSkillId": "optional-existing-skill-id",
    "categoryId": "tenant-category-id",
    "connectorOperationId": "tenant-operation-id",
    "roleIds": ["tenant-role-id"]
  }
  ```

  The API must require `targetSkillId` for `NEW_DRAFT_VERSION`, require a valid category/operation/role mapping for a publishable draft, and always create only `DRAFT`. Package `metadata.lingxi.connector_key` and `operation_key` are display-only candidates until the administrator selects a current registry operation. A same-key import cannot silently overwrite an existing Skill. The imported body and allowed references/assets are stored in `package_manifest`; scripts are never stored as executable content.

- [ ] **Step 5: Implement safe export.**

  `GET /skills/{skill_id}/export` exports the selected published version as a ZIP containing the normalized `SKILL.md` plus safe `references/` and `assets/`. Rebuild frontmatter from platform-safe fields and omit tenant IDs, role IDs/names, connector IDs/keys, endpoint templates, connection configuration, encrypted or plaintext secrets, raw inputs, results, artifacts, and audit events. Export must be deterministic for the same version so package hash tests are stable.

- [ ] **Step 6: Run import/export/security tests.**

  ```powershell
  pytest server/tests/test_skill_import.py server/tests/security/test_skill_security.py -q
  ```

  Expected: PASS; valid packages become un published drafts, malicious packages are rejected before extraction, conflicts require an explicit choice, and exported archives contain no privileged runtime data.

- [ ] **Step 7: Commit package support.**

  ```powershell
  git add server/app/services/skill_package_service.py server/app/api/v1/skill_imports.py server/app/schemas/skill_import.py server/app/services/skill_audit_service.py server/tests/test_skill_import.py server/tests/security/test_skill_security.py server/app/core/config.py
  git commit -m "feat: securely import and export skill packages"
  ```

### Task 7: Add private user SkillPreset support (M3)

**Files:**
- Create: `server/app/repositories/skill_preset_repo.py`
- Create: `server/app/services/skill_preset_service.py`
- Modify: `server/app/api/v1/skills.py`
- Modify: `server/app/schemas/skill.py`
- Create: `server/tests/test_skill_preset.py`

- [ ] **Step 1: Write failing privacy and preset tests.**

  ```python
  def test_user_can_favorite_and_save_defaults_for_published_skill(...): ...
  def test_preset_default_input_is_validated_against_current_schema(...): ...
  def test_user_cannot_save_connector_or_role_fields_in_preset(...): ...
  def test_preset_is_private_to_user_and_tenant(...): ...
  def test_user_cannot_create_shared_skill_or_publish_preset(client, employee_token):
      assert client.post("/api/v1/skills", headers=employee_token, json={}).status_code == 403
      assert client.post("/api/v1/skill-presets/publish", headers=employee_token, json={}).status_code == 404
  def test_disabled_skill_hides_or_marks_preset_unavailable(...): ...
  ```

- [ ] **Step 2: Run the tests and verify the preset service/routes are absent.**

  ```powershell
  pytest server/tests/test_skill_preset.py -q
  ```

  Expected: FAIL with missing repository/service behavior.

- [ ] **Step 3: Implement the private preset model behavior and endpoints.**

  Use the already-migrated `skill_presets` table and expose only these fields. The table may exist for migration compatibility before M3, but routes and UI remain disabled until `SKILLS_M3_IMPORTS_ENABLED=true`:

  ```json
  {
    "displayName": "我的报表",
    "isFavorite": true,
    "defaultInput": {"format": "xlsx"},
    "displayOrder": 1
  }
  ```

  Add:

  | Method | Path | Permission | Behavior |
  |---|---|---|---|
  | `GET` | `/skills/{skill_id}/preset` | `SKILL_READ` | Current user's private preset or empty defaults. |
  | `PUT` | `/skills/{skill_id}/preset` | `SKILL_READ` | Upsert favorite/name/order/default input. |
  | `DELETE` | `/skills/{skill_id}/preset` | `SKILL_READ` | Remove the user's private customization. |
  | `GET` | `/skill-presets` | `SKILL_READ` | User's own presets joined to available published Skills. |

  The service must first resolve the current available published version and validate `defaultInput` against its normalized schema. It must strip/deny unknown properties and deny all runtime-control properties even if the user attempts to submit them. It must cap display name length, input JSON size, and total preset count. The SQL query always filters both `tenant_id` and `user_id`.

- [ ] **Step 4: Test the preset API and commit.**

  ```powershell
  pytest server/tests/test_skill_preset.py server/tests/test_skills_api.py -q
  git add server/app/repositories/skill_preset_repo.py server/app/services/skill_preset_service.py server/app/api/v1/skills.py server/app/schemas/skill.py server/tests/test_skill_preset.py
  git commit -m "feat: add private skill presets"
  ```

  Expected: PASS; users can personalize the system catalog without creating, sharing, publishing, or changing a Tool Skill.

### Task 8: Implement the Skill execution engine, Inline Demo/Celery drivers, audit events, and artifacts (M1/M2/M3)

**Files:**
- Create: `server/app/repositories/skill_execution_repo.py`
- Create: `server/app/services/skill_execution_service.py`
- Create: `server/app/services/skill_artifact_service.py`
- Create: `server/app/integrations/skills/artifacts.py`
- Create: `server/app/tasks/skill_tasks.py`
- Create: `server/app/api/v1/skill_executions.py`
- Modify: `server/app/schemas/skill_execution.py`
- Modify: `server/app/tasks/celery_app.py`
- Modify: `server/app/core/config.py`
- Create: `server/tests/test_skill_execution.py`
- Create: `server/tests/test_skill_sse.py`
- Modify: `server/tests/security/test_skill_security.py`

- [ ] **Step 1: Write failing execution state-machine and redaction tests.**

  Cover the M1 driver contract and M2/M3 operational behavior. M1 assertions must use `local_demo_gate` and a fixed Handler; tests for `SKILL_EXECUTE`, tenant/role snapshots, Connector availability, audit fail-closed, timeout/cancel, artifact authorization and retry are marked m2 or m3:

  ```python
  def test_unauthorized_skill_is_rejected_before_connector_call(...): ...
  def test_execution_locks_current_published_version_and_operation(...): ...
  def test_execution_state_machine_rejects_running_to_queued(...): ...
  def test_input_is_validated_against_server_schema_not_client_version(...): ...
  def test_duplicate_idempotency_key_returns_same_execution(...): ...
  def test_audit_write_failure_fails_closed_and_does_not_enqueue(...): ...
  def test_connector_secret_and_sensitive_output_are_redacted(...): ...
  def test_timeout_marks_timed_out_and_does_not_leak_traceback(...): ...
  def test_cancel_is_only_sent_when_operation_supports_cancel(...): ...
  def test_retry_creates_new_execution_with_retry_of_reference(...): ...
  def test_artifact_download_rechecks_tenant_user_and_role(...): ...
  ```

  Add a fake operation that records calls so a rejected request can assert zero connector invocations.

- [ ] **Step 2: Run focused tests and confirm the service/worker are absent.**

  ```powershell
  pytest server/tests/test_skill_execution.py server/tests/test_skill_sse.py -q
  ```

  Expected: FAIL with missing service, repository, and task symbols.

- [ ] **Step 3: Implement server-side preflight and state transitions.**

  `SkillExecutionService.create` receives `AccessContext`, `chat_session_id`, `skill_id`, `input`, and an `idempotency_key` from a request header. In M1, `AccessContext` is the loopback local-demo context and the service selects the fixed `customer_report_search` Handler; in M2/M3 it is the authenticated tenant context and the service selects the server-resolved Connector Operation. It performs this ordered transaction before executing/enqueueing:

  1. Resolve the current tenant's Skill by ID; never accept version, connector, operation, role, URL, SQL, or credentials from the request body.
  2. Check `SKILL_EXECUTE`, `CHAT_WRITE`, session ownership, active category, Skill `PUBLISHED`, current published version, role grant, active Connector, active Operation, and tenant connection.
  3. Validate input against the locked version's normalized schema and operation contract; reject unknown fields and size/format violations.
  4. Build a role snapshot from `AccessContext`, redact the input with the schema's sensitive paths, and create `SkillExecution(status="PENDING")` with version/operation snapshots and a generated request ID.
  5. Write the initial `skill_run_started` audit/event row in the same transaction. If this insert fails, roll back and do not enqueue.
  6. In M1 execute through the inline Demo driver after commit and persist the same event contract; in M2/M3 enqueue the Celery task with execution ID. If queue submission fails, persist a safe `QUEUE_FAILED` terminal error and emit no success event.

  Use the design state machine exactly:

  ```text
  PENDING -> VALIDATING -> QUEUED -> RUNNING -> SUCCEEDED
                              |         |------> FAILED
                              |         |------> TIMED_OUT
                              |         |------> CANCELED
                              +-------> REJECTED
  ```

  Store every transition as a sequenced event with only safe status labels and progress messages.

- [ ] **Step 4: Implement the Inline Demo driver, then the Celery task and operation execution context.**

  M1 implements `InlineDemoSkillExecutionDriver` with a deterministic `customer_report_search` handler and no network/credential/file access. M2/M3 `skill_tasks.py` opens its own `SessionLocal` session, re-reads the execution and locked version, transitions to `VALIDATING`, calls the registry Operation availability check, then transitions to `RUNNING`. It passes a `SkillExecutionContext` containing cancellation signal, redacted logger, tenant/user/role snapshot, and artifact writer. It must never trust a mutable current Skill pointer after the execution was created.

  On a successful result, sanitize structured data using output contract and `presentation_config`, redact configured paths, cap rows/bytes, persist an optional artifact, append `skill_run_result`, `skill_run_artifact`, and `skill_run_done`, and set `SUCCEEDED`. On connector error, persist only an allowlisted safe error code/message and set `FAILED`. On Celery soft/hard time limit, request cancellation where supported and set `TIMED_OUT`. On user cancellation, set `CANCELED` only after the operation confirms cancellation or the policy allows a safe terminal cancellation.

  Configure per-operation timeout ceiling, queue, max retries, concurrency, result size, and artifact TTL in `execution_policy`; a Skill cannot raise an operation's ceiling. Use the existing task reliability helpers for retry backoff and never retry non-idempotent writes unless the operation explicitly declares retry safety.

- [ ] **Step 5: Implement execution, cancel, retry, and artifact APIs.**

  Add:

  | Method | Path | Permission | Behavior |
  |---|---|---|---|
  | `GET` | `/skill-executions/{execution_id}` | owner or `SKILL_AUDIT_READ` | Safe status/result/event summary. |
  | `POST` | `/skill-executions/{execution_id}/cancel` | owner or `SKILL_MANAGE` | Idempotent cancel request. |
  | `POST` | `/skill-executions/{execution_id}/retry` | owner or `SKILL_MANAGE` | Re-resolve permission/current availability; create a new execution, never mutate the old one. |
  | `GET` | `/skill-artifacts/{artifact_id}/download` | owner plus current Skill access | Short-lived signed redirect after second authorization check. |

  The admin test endpoint under `POST /skills/{skill_id}/versions/{version_id}/test-runs` must use the same execution service with an admin test flag; it still performs all connector and audit checks and displays a side-effect confirmation for external writes.

- [ ] **Step 6: Implement bounded artifact storage and safe response serialization.**

  `SkillArtifactService` accepts only storage keys created by the operation's artifact writer, normalizes filenames to a safe basename, checks MIME/extension and size, computes a checksum, sets expiry, and stores no raw path from user input. Downloads require tenant, user, current role, Skill status, and artifact expiry checks. API responses include `artifactId`, safe filename, MIME, size, expiry, and download capability, never a storage key or signed URL before the authorization check.

- [ ] **Step 7: Run execution, SSE, and security tests, then commit.**

  ```powershell
  pytest server/tests/test_skill_execution.py server/tests/test_skill_sse.py server/tests/security/test_skill_security.py -q
  ```

  Expected: PASS; all rejected requests avoid connector calls, all terminal states are auditable, secrets and tracebacks are absent from user results, and artifact downloads are tenant/user checked.

  ```powershell
  git add server/app/repositories/skill_execution_repo.py server/app/services/skill_execution_service.py server/app/services/skill_artifact_service.py server/app/integrations/skills/artifacts.py server/app/tasks/skill_tasks.py server/app/api/v1/skill_executions.py server/app/schemas/skill_execution.py server/app/tasks/celery_app.py server/app/core/config.py server/tests/test_skill_execution.py server/tests/test_skill_sse.py server/tests/security/test_skill_security.py
  git commit -m "feat: execute tool skills safely"
  ```

### Task 9: Integrate Tool Skill runs with Chat sessions and SSE (M1/M2)

**Files:**
- Create: `server/app/db/migrations/versions/0010_skill_chat_links.py`
- Modify: `server/app/models/chat.py`
- Modify: `server/app/schemas/chat.py`
- Modify: `server/app/repositories/chat_repo.py`
- Modify: `server/app/api/v1/chat.py`
- Modify: `server/app/services/chat_service.py`
- Modify: `server/app/services/sse_service.py`
- Modify: `server/app/api/v1/__init__.py`
- Create: `server/tests/test_skill_chat_api.py`
- Modify: `server/tests/test_chat_sse.py`

- [ ] **Step 1: Write failing Chat integration tests.**

  Add milestone-specific tests for the local-demo gate or authenticated ownership, request shape, message persistence, SSE event order, and ordinary Chat isolation:

  ```python
  def test_skill_run_requires_chat_session_owner_and_skill_execute(...): ...
  def test_skill_run_body_accepts_only_skill_id_and_input(...): ...
  def test_skill_run_creates_linked_request_message_and_execution(...): ...
  def test_skill_sse_emits_design_event_sequence(...): ...
  def test_skill_sse_heartbeat_does_not_change_event_order(...): ...
  def test_normal_message_run_never_auto_invokes_a_skill(...): ...
  def test_session_messages_include_safe_skill_metadata(...): ...
  ```

- [ ] **Step 2: Run the tests and confirm the Chat endpoint/fields are absent.**

  ```powershell
  pytest server/tests/test_skill_chat_api.py server/tests/test_chat_sse.py -q
  ```

  Expected: FAIL with 404 or missing model/schema fields.

- [ ] **Step 3: Add Chat message links and migration `0010_skill_chat_links.py`.**

  Add `message_type` to `ChatMessage` with `TEXT`, `SKILL_REQUEST`, and `SKILL_RESULT` values, plus `skill_execution_id` and safe `message_metadata` JSON. Add nullable `request_message_id` and `result_message_id` foreign keys on `SkillExecution` if not already present. The migration must use the current `0009_tool_skills` revision, preserve all existing messages as `TEXT`, and downgrade without deleting chat data.

- [ ] **Step 4: Add the Chat skill-run endpoint and service boundary.**

  Implement:

  ```text
  POST /api/v1/chat/sessions/{session_id}/skill-runs
  body: {"skillId": "...", "input": {...}}
  required permissions: CHAT_WRITE + SKILL_EXECUTE
  response: text/event-stream
  ```

  The route validates the session before opening the stream, applies the M1 local-demo gate or M2/M3 authenticated tenant and permission checks, calls `SkillExecutionService.create`, persists a `SKILL_REQUEST` message with a safe rendered summary, then streams status events. It must not pass client `skillVersionId`, `connectorKey`, `operationKey`, role, URL, SQL, or credentials through to the service. The result message is created/updated from safe result data only. If a request fails before streaming, return the project's structured 4xx error with request ID.

- [ ] **Step 5: Emit the exact Skill SSE event contract.**

  Extend `SseService` and the Skill stream adapter with these event names and minimum fields:

  | Event | Fields |
  |---|---|
  | `skill_run_started` | `executionId`, `skillId`, `version` |
  | `skill_run_status` | `executionId`, `status`, `label` |
  | `skill_run_progress` | `executionId`, optional `percent`, `message` |
  | `skill_run_result` | `executionId`, `summary`, optional safe `data` |
  | `skill_run_artifact` | `executionId`, `artifactId`, `fileName` |
  | `skill_run_error` | `executionId`, safe `code`, `message`, `retryable` |
  | `skill_run_done` | `executionId`, `status`, `durationMs` |

  Reuse the existing heartbeat comment behavior. Events must be replayable from persisted `SkillExecutionEvent` sequence values after a disconnect; the client must not assume a stream-only event is the source of truth.

- [ ] **Step 6: Preserve ordinary Chat behavior and test both paths.**

  Keep `POST /chat/sessions/{session_id}/message-runs` unchanged for natural-language Chat. `ChatService` must not inspect message text to select a Skill. The only Skill entry point is explicit user action through `skill-runs`. List-message serialization must include `messageType`, `skillExecutionId`, and safe metadata for Skill cards while keeping ordinary messages backward compatible.

- [ ] **Step 7: Run migrations and Chat tests, then commit.**

  ```powershell
  pytest server/tests/test_skill_chat_api.py server/tests/test_chat_sse.py server/tests/test_chat_sse.py -q
  alembic -c server/alembic.ini upgrade head
  git add server/app/db/migrations/versions/0010_skill_chat_links.py server/app/models/chat.py server/app/schemas/chat.py server/app/repositories/chat_repo.py server/app/api/v1/chat.py server/app/services/chat_service.py server/app/services/sse_service.py server/app/api/v1/__init__.py server/tests/test_skill_chat_api.py server/tests/test_chat_sse.py
  git commit -m "feat: connect tool skills to chat"
  ```

  Expected: PASS; a user can explicitly start a Skill run inside an owned Chat session and ordinary model messages remain unchanged.

### Task 10: Build the administrator Skills navigation, list, and category pages

**阶段切片：**

- **M1：** 只在 `SKILLS_M1_LOCAL_DEMO_MODE=true` 且请求来自 loopback 时开放 Skills 列表、分类管理和编辑器入口；不检查真实登录或 `SKILL_MANAGE`，不显示导入、Connector、审计、版本历史、角色授权和 Operation 筛选。
- **M2：** 切换到真实会话和租户上下文；列表、分类和每个管理动作分别检查 `SKILL_MANAGE`、`SKILL_CATEGORY_MANAGE`、`SKILL_AUDIT_READ`、`SKILL_CONNECTOR_MANAGE`，并增加版本、授权角色和 Operation 信息。
- **M3：** 在 M2 的权限门禁上开放导入/导出、Connector 运营和高级统计入口；收藏、默认参数、显示名称和排序属于 Chat 侧私有 `SkillPreset`，不在管理员列表中伪装成共享 Skill 字段。

**Files:**
- Modify: `web/admin/src/routes/index.tsx`
- Modify: `web/admin/src/api/queryClient.ts`
- Create: `web/admin/src/features/skills/types.ts`
- Create: `web/admin/src/features/skills/api/skillApi.ts`
- Create: `web/admin/src/features/skills/api/categoryApi.ts`
- Create: `web/admin/src/features/skills/hooks/useSkillQueries.ts`
- Create: `web/admin/src/features/skills/hooks/useSkillMutations.ts`
- Create: `web/admin/src/features/skills/pages/SkillPage.tsx`
- Create: `web/admin/src/features/skills/pages/SkillCategoriesPage.tsx`
- Create: `web/admin/src/features/skills/components/SkillList.tsx`
- Create: `web/admin/src/features/skills/components/SkillCategoryPanel.tsx`
- Create: `web/admin/src/features/skills/components/ConfirmActionDialog.tsx`
- Modify: `web/admin/src/styles/index.css`
- Create: `web/admin/src/styles/skills.css`
- Create: `web/admin/src/features/skills/utils/skillFormValidation.ts`
- Create: `web/admin/src/features/skills/utils/skillFormValidation.test.ts`

- [ ] **Step 1: Write failing front-end validation and route tests.**

  Use the repository's TypeScript test setup after adding Vitest in this task. Assert that management routes are permission-gated and that client helpers reject unsafe fields before the request is sent:

  ```ts
  it('accepts only TOOL in phase one', () => {
    expect(validateSkillMetadata({ skillType: 'TOOL' }).valid).toBe(true);
    expect(validateSkillMetadata({ skillType: 'PROMPT' }).valid).toBe(false);
  });

  it('does not allow connector, operation, role, URL, SQL, or credentials in user input', () => {
    expect(filterRuntimeFields({ connectorKey: 'x', input: { sql: 'select 1' } })).toEqual({ input: {} });
  });

  it('[M1] allows the Skills catalog only for loopback local-demo identity', () => {
    expect(visibleRoutesFor({ localDemoMode: true, isLoopback: true })).toContain('#skills');
    expect(visibleRoutesFor({ localDemoMode: true, isLoopback: false })).not.toContain('#skills');
    expect(visibleRoutesFor({ localDemoMode: false, permissions: [] })).not.toContain('#skills');
  });

  it('[M2] hides management routes without the matching server permission', () => {
    expect(visibleRoutesFor({ permissions: ['SKILL_READ'] })).not.toContain('#skills');
    expect(visibleRoutesFor({ permissions: ['SKILL_MANAGE'] })).toContain('#skills');
    expect(visibleRoutesFor({ permissions: ['SKILL_MANAGE'] })).not.toContain('#skills/audit');
  });
  ```

- [ ] **Step 2: Add the front-end test runner and confirm tests fail.**

  Add `vitest`, `jsdom`, and the existing React test utilities only if required by component tests. Add `"test": "vitest run"` and `"test:watch": "vitest"` to `web/admin/package.json`. Run:

  ```powershell
  cd web/admin
  npm test -- --run src/features/skills/utils/skillFormValidation.test.ts
  ```

  Expected: FAIL because the validation module and route entry do not exist.

- [ ] **Step 3: Add typed API/query contracts and permission-gated routes.**

  Define types for category, Skill summary, version, validation issue, operation summary, role grant, and mutation payload. Add query keys for categories, skills, skill details, versions, operations, presets, executions, and audit. Use the existing `apiRequest` helper and invalidate only affected keys after mutations.

  Implement routes with a phase-aware server gate:

  ```text
  M1 #skills              -> SkillPage          (local-demo gate + loopback)
  M1 #skills/categories   -> SkillCategoriesPage(local-demo gate + loopback)
  M1 #skills/new          -> SkillEditorPage    (local-demo gate + loopback, hidden)
  M1 #skills/:id          -> SkillEditorPage    (local-demo gate + loopback, hidden)

  M2 #skills              -> SkillPage          (SKILL_MANAGE)
  M2 #skills/categories   -> SkillCategoriesPage(SKILL_CATEGORY_MANAGE)
  M2 #skills/new          -> SkillEditorPage    (SKILL_MANAGE, hidden)
  M2 #skills/:id          -> SkillEditorPage    (SKILL_MANAGE, hidden)
  M2 #skills/connectors   -> SkillConnectorsPage(SKILL_CONNECTOR_MANAGE, read-only registry)
  M2 #skills/audit        -> SkillAuditPage     (SKILL_AUDIT_READ, hidden)

  M3 #skills/import       -> SkillImportPage    (SKILL_MANAGE, hidden)
  M3 #skills/connectors   -> SkillConnectorsPage(SKILL_CONNECTOR_MANAGE, full operations)
  M3 #skills/audit        -> SkillAuditPage     (SKILL_AUDIT_READ, advanced filters)
  ```

  Extend `SidebarIconName` with `skills`. In M1 the sidebar item is visible only after the local-demo gate passes. In M2/M3 it is visible when the user has a relevant management permission, but the route renderer must still check the individual permission so typing a hash cannot bypass the gate. Failed gates render a safe 403/feature-disabled state with request ID.

- [ ] **Step 4: Implement the Skills list page.**

  `SkillPage` uses one component shell with phase-gated controls:

  - **M1 local-demo：** title/count, “新建 Tool Skill”, “分类管理”, search by key/name/description, columns for icon/name/key/category/type/status/updated time, and open/edit/validate/first-publish actions. It must not render import, Connector, audit, Operation, role, version-history, rollback or export controls.
  - **M2 secure-operations：** add real-tenant filters for category/status/Operation/authorized role, current version and lifecycle columns, execution/failure counts, create-draft-version, test, publish, disable/enable, rollback-as-new-version and archive actions. Each action requires the server-authoritative response and the matching management permission.
  - **M3 production-governance：** add import/export, Connector health and advanced audit entry points according to independent permissions; never show user favorites, display names, default parameters or personal order as shared Skill metadata.
  - **All phases：** search uses server-side debounce; show blocking validation tooltips, empty/loading/error states with request ID, pagination, responsive cards below 900px, and never infer availability from a status badge.

  Every mutation invalidates only affected detail/list/version queries and relies on the API response rather than client-side status inference.

- [ ] **Step 5: Implement category management.**

  `SkillCategoriesPage` and `SkillCategoryPanel` support create/edit, icon selection from a fixed safe set, display order, active/disabled state, counts, and drag-free up/down ordering buttons. In M1 they operate only in the loopback local-demo namespace and use the same local gate as the list; in M2/M3 every read/write carries the authenticated tenant context and requires `SKILL_CATEGORY_MANAGE`. Disabling requires `ConfirmActionDialog` text explaining that existing history remains but new Chat executions stop. Delete is shown only when the server reports zero references; otherwise show “停用” and the conflict reason.

- [ ] **Step 6: Run front-end checks and commit the navigation/list slice.**

  ```powershell
  cd web/admin
  npm test -- --run src/features/skills/utils/skillFormValidation.test.ts
  npm run typecheck
  npm run lint
  npm run build
  ```

  Expected: PASS; M1 routes work only behind the loopback local-demo gate, M2 routes enforce real permissions, and the build contains no hidden-button-only authorization path. Do not ship import, Connector or audit routes in the M1 artifact.

  ```powershell
  git add web/admin/package.json web/admin/package-lock.json web/admin/src/routes/index.tsx web/admin/src/api/queryClient.ts web/admin/src/features/skills web/admin/src/styles/index.css web/admin/src/styles/skills.css
  git commit -m "feat: add skills admin catalog"
  ```

### Task 11: Build the administrator Tool Skill editor and publish workflow

**阶段切片：**

- **M1：** 完成基本信息、内联 `SKILL.md`、受限输入 Schema、展示策略、服务端校验、保存草稿和首次发布；执行绑定固定为 `customer_report_search` Demo Handler，不显示 Operation、角色和版本运营控件。
- **M2：** 增加服务端预注册 `knowledge-base.search` fake Connector Operation 选择、Operation 契约、角色授权、不可变版本、差异、停用/归档/回滚和发布确认；此阶段才要求真实 `SKILL_MANAGE`、角色授权和执行权限链路。
- **M3：** 由 Task 12 接入包导入和更多 Operation；编辑器只接收安全映射结果，不把脚本、URL、SQL 或凭据变成可执行配置。

**Files:**
- Create: `web/admin/src/features/skills/pages/SkillEditorPage.tsx`
- Create: `web/admin/src/features/skills/components/SkillEditorSteps.tsx`
- Create: `web/admin/src/features/skills/components/SkillForm.tsx`
- Create: `web/admin/src/features/skills/components/OperationSelector.tsx`
- Create: `web/admin/src/features/skills/components/InputSchemaEditor.tsx`
- Create: `web/admin/src/features/skills/components/SchemaFieldRow.tsx`
- Create: `web/admin/src/features/skills/components/PresentationPolicyPanel.tsx`
- Create: `web/admin/src/features/skills/components/SkillRoleGrantPanel.tsx`
- Create: `web/admin/src/features/skills/components/SkillVersionPanel.tsx`
- Create: `web/admin/src/features/skills/components/ValidationSummary.tsx`
- Create: `web/admin/src/features/skills/components/ConfirmActionDialog.tsx`
- Create: `web/admin/src/features/skills/components/SkillExecutionPanel.tsx`
- Modify: `web/admin/src/features/skills/types.ts`
- Modify: `web/admin/src/features/skills/hooks/useSkillQueries.ts`
- Modify: `web/admin/src/features/skills/hooks/useSkillMutations.ts`
- Modify: `web/admin/src/features/skills/utils/skillFormValidation.ts`
- Create: `web/admin/tests/t20_tool_skill_admin_playwright.py`

- [ ] **Step 1: Write phase-specific editor validation tests.**

  M1 tests must not require an Operation or role grant:

  ```ts
  it('[M1] builds a Tool Skill draft bound to the fixed Demo Handler', () => {
    const payload = toSkillDraftPayload({
      phase: 'M1',
      basic: { key: 'customer-report-search', name: '客户报表查询', categoryId: 'cat-1' },
      fields: [{ name: 'query', type: 'text', required: true }],
      demoHandlerKey: 'customer_report_search',
    });
    expect(payload).toMatchObject({ skillType: 'TOOL', demoHandlerKey: 'customer_report_search' });
    expect(payload).not.toHaveProperty('connectorOperationId');
    expect(payload).not.toHaveProperty('roleIds');
    expect(JSON.stringify(payload)).not.toContain('password');
  });

  it('[M1] blocks publish for an invalid schema without requiring Operation or role', () => {
    const codes = getPublishBlockers(invalidM1Draft).map((item) => item.code);
    expect(codes).toContain('INPUT_SCHEMA_INVALID');
    expect(codes).not.toContain('OPERATION_REQUIRED');
    expect(codes).not.toContain('ROLE_REQUIRED');
  });
  ```

  Add separate M2 tests for the secure editor contract:

  ```ts
  it('[M2] serializes only a server-listed Operation and role IDs', () => {
    const payload = toSkillDraftPayload({
      phase: 'M2',
      basic: { key: 'customer-report-export', name: '客户报表导出', categoryId: 'cat-1' },
      operationId: 'operation-knowledge-base-search',
      fields: [{ name: 'query', type: 'text', required: true }],
      roles: ['role-report-operator'],
    });
    expect(payload).toMatchObject({ skillType: 'TOOL', connectorOperationId: 'operation-knowledge-base-search' });
    expect(JSON.stringify(payload)).not.toContain('connectorKey');
    expect(JSON.stringify(payload)).not.toContain('password');
  });

  it('[M2] blocks publish when Operation, role, or policy ceiling is missing', () => {
    const codes = getPublishBlockers(incompleteM2Draft).map((item) => item.code);
    expect(codes).toEqual(expect.arrayContaining(['OPERATION_REQUIRED', 'ROLE_REQUIRED', 'POLICY_EXCEEDS_CEILING']));
  });

  it('[M2] requires confirmation for external writes and file writes', () => {
    expect(policyForOperation({ sideEffectLevel: 'EXTERNAL_WRITE' }).requiresConfirmation).toBe(true);
    expect(policyForOperation({ sideEffectLevel: 'FILE_WRITE' }).requiresConfirmation).toBe(true);
  });

  it('[M2] never changes a published version in place', () => {
    expect(editorMode({ versionStatus: 'PUBLISHED', phase: 'M2' })).toBe('CREATE_DRAFT_VERSION');
  });
  ```

- [ ] **Step 2: Run the tests and confirm the editor modules are absent.**

  ```powershell
  cd web/admin
  npm test -- --run src/features/skills/utils/skillFormValidation.test.ts
  ```

  Expected: FAIL with missing editor helper functions/components.

  M1 keeps a single local-demo draft/published pointer; M2 enables server-issued version IDs, optimistic locks, role grants and immutable version history. The same editor component must not expose later-phase fields merely because they exist in the database schema.

- [ ] **Step 3: Implement the editor data model and step shell.**

  `SkillEditorPage` loads `GET /skills/{id}` or creates a new shell with `POST /skills`. It maintains a single draft state with these sections:

  ```ts
  type SkillEditorState = {
    basic: {
      key: string;
      name: string;
      description: string;
      icon: string;
      categoryId: string;
      skillType: 'TOOL';
    };
    package: { markdownBody: string; references: string[]; assets: string[] };
    operationId: string | null;
    inputSchema: ToolInputSchema;
    presentationConfig: PresentationConfig;
    executionPolicy: ExecutionPolicy;
    roleIds: string[];
    versionId: string;
    optimisticLock: number;
  };
  ```

  Render a breadcrumb (`Skills / 新建` or `Skills / {name}`), status/version badge, “保存草稿”, “验证”, “测试运行”, “发布”, and overflow actions. Step navigation must display completion/error badges and prevent leaving with unsaved changes unless the user confirms. The server is the source of the version ID and optimistic lock; do not generate a version ID in the browser.

- [ ] **Step 4: Implement the Basic Information step.**

  `SkillForm` fields and rules:

  - `key`: stable lowercase identifier, generated from name only on first input, editable before first publish, not editable after a published version exists; show uniqueness validation from API.
  - `name`: Chinese/English display name, required, max 120 characters.
  - `description`: purpose and scope, required, max 1024 characters; show the text that will appear in Chat.
  - `icon`: fixed safe icon set, no arbitrary URL or uploaded HTML/SVG.
  - `category`: active category select; disabled categories are not selectable.
  - `skillType`: fixed “Tool Skill（第一期）” read-only value; do not show an enabled Prompt option.

  Include a right-side “Chat preview” card showing icon, name, description, category, side-effect level, and current status. The preview must not display connector internals or role IDs.

- [ ] **Step 5: Implement the Agent Skills package/document step.**

  Provide a markdown textarea with a frontmatter preview rather than an executable file editor. The form creates a normalized `SKILL.md` from `name`, `description`, `metadata.lingxi` candidate values, and the body. Show a collapsible “标准说明” panel with the required frontmatter and allowed `references/`/`assets/` folders. Show explicit security text: scripts, code files, credentials, arbitrary URLs, and free SQL are not accepted.

  If the Skill originated from an import, show the immutable package hash, file scan summary, and safe references/assets. The editor may change the description/body and mapping fields in the new draft, but it cannot revive a rejected package entry or attach a script. Client preview is informational; server validation is mandatory.

  In M1 this step is replaced by a read-only card showing `customer_report_search`; there is no Operation selector or editable handler field. The selector and all Operation-related validation below are M2 behavior.

- [ ] **Step 6: Implement Operation selection with a read-only contract.**

  `OperationSelector` loads only active operations from `GET /skill-connectors/{connectorKey}/operations` or a tenant-safe aggregated endpoint. Display connector display name, operation display name, side-effect badge, input/output contract summary, timeout ceiling, cancellation support, retry safety, and required connection health. Never display secret values, internal endpoint templates, or editable connector/operation key text.

  Selecting an operation updates the local schema defaults and policy ceiling but never changes the operation by editing a hidden field. If the operation becomes disabled, show a blocking warning and require re-selection. The test and publish buttons remain disabled until a valid operation is selected.

- [ ] **Step 7: Implement the structured Input Schema builder.**

  `InputSchemaEditor` supports safe field rows with:

  | UI type | JSON type/format | Controls |
  |---|---|---|
  | Single-line text | `string` | label, description, required, min/max length. |
  | Long text | `string` | label, description, required, max length. |
  | Integer/number | `integer`/`number` | min/max, required. |
  | Boolean | `boolean` | default, required. |
  | Date/date-time | `string` + allowed format | required, range. |
  | Enum | `string` + `enum` | safe option labels/values. |
  | File reference | platform file-ref type | source permission, size/MIME limits. |
  | Array of scalar/enum | `array` | item type and max items. |

  The root is always an object with `additionalProperties: false`. `SchemaFieldRow` supports reorder, duplicate, delete, required toggle, and field-level validation. Field names must be machine-safe and cannot be any runtime-control name. Render the generated JSON Schema in read-only mode with a copy button; do not allow pasting arbitrary JSON that bypasses the builder. Imported schemas are normalized into the same supported subset and show rejected paths in `ValidationSummary`.

- [ ] **Step 8: Implement presentation and execution policy controls.**

  `PresentationPolicyPanel` contains separate cards:

  1. **Form display:** labels, help text, placeholder, field order, required marker, and whether a default is shown.
  2. **Result display:** summary template, allowed structured paths, table columns, max rows, copy enabled, artifact display, and sensitive paths to redact.
  3. **Execution policy:** timeout, max retries, per-user rate limit, concurrency limit, result byte limit, artifact TTL, idempotency mode, side-effect label, and confirmation text.

  Render the selected Operation ceiling next to each numeric control. Inputs above the ceiling are rejected immediately in the UI and again by the server. For `EXTERNAL_WRITE` and `FILE_WRITE`, confirmation is mandatory and the confirmation text must state the effect in plain language. Never expose credential configuration, raw headers, SQL, URL templates, or arbitrary code controls in this panel.

  M1 must hide this step completely. Enable it only after the authenticated M2 management API confirms `SKILL_MANAGE` and the tenant role catalog.

- [ ] **Step 9: Implement role authorization and version review.**

  `SkillRoleGrantPanel` loads tenant roles, shows role names/descriptions, and allows a checklist of roles. It displays a clear warning when no role is selected and explains that this controls Chat visibility/execution. The UI submits role IDs only to the management endpoint; the user execution client never receives them.

  `SkillVersionPanel` shows version timeline, current status, created/published actor/time, package hash, and a redacted diff between selected versions. For a published version, the primary edit action is “创建草稿版本”. Rollback must create a new draft/published version through the API, not mutate history. Show a side-effect confirmation before test runs and publish only after server validation succeeds.

- [ ] **Step 10: Implement validate, test, publish, and lifecycle controls.**

  - “保存草稿” calls `POST /skills/{skillId}/versions` or the draft PATCH endpoint, preserves server version/lock, and shows request ID.
  - “验证” calls the version validation endpoint and renders `ValidationSummary` grouped into blocking errors and warnings with clickable step/path links.
  - “测试运行” opens `SkillExecutionPanel` with generated form data; it requires a second confirmation for external/file writes, uses the admin test endpoint, and renders the same safe status/result/artifact card used by Chat.
  - “发布” is disabled until the last server validation is valid, then opens a summary dialog listing category, operation, roles, policy, side-effect level, and version. After confirmation it calls publish and refreshes list/detail queries.
  - “停用/启用/归档/回滚/导出” use `ConfirmActionDialog` with explicit consequences and are only rendered when the server says the transition is legal.
  - On `409 OPTIMISTIC_LOCK_CONFLICT`, reload the current version and show a diff; never overwrite silently.

- [ ] **Step 11: Add administrator browser acceptance coverage.**

  `t20_tool_skill_admin_playwright.py` must log in as the seeded administrator and verify:

  1. Skills navigation is visible to `SYSTEM_ADMIN` and hidden from an employee.
  2. The admin creates category “数据分析”, creates `customer-report-export`, selects `database-readonly.run-template` or the seeded reporting operation, adds fields, adds a role, saves a draft, and sees the version badge.
  3. Invalid schema/policy shows blocking errors and does not enable publish.
  4. A valid safe test run shows `PENDING/RUNNING/SUCCEEDED` or a safe controlled failure.
  5. Publish shows the confirmation summary and the list changes to `PUBLISHED`.
  6. Editing the published Skill creates a new draft and leaves the published version/history unchanged.
  7. Disable hides the Skill from the availability endpoint and the UI explains the effect.

- [ ] **Step 12: Run front-end tests and commit the editor slice.**

  ```powershell
  cd web/admin
  npm test -- --run src/features/skills/utils/skillFormValidation.test.ts
  npm run typecheck
  npm run lint
  npm run build
  cd ../..
  pytest web/admin/tests/t20_tool_skill_admin_playwright.py -q
  ```

  Expected: PASS; the administrator can complete the full create → validate → test → publish workflow without exposing or editing forbidden runtime controls.

  ```powershell
  git add web/admin/src/features/skills/pages/SkillEditorPage.tsx web/admin/src/features/skills/components web/admin/src/features/skills/types.ts web/admin/src/features/skills/hooks web/admin/src/features/skills/utils web/admin/tests/t20_tool_skill_admin_playwright.py
  git commit -m "feat: add tool skill administrator editor"
  ```

### Task 12: Build import/export, Connector, and audit management pages

**阶段切片：**

- **M1：** 本任务的页面/API 不注册、不打包到可用路由；M1 只使用 Skills 列表、分类和编辑器。
- **M2：** 开放脱敏审计页面和只读服务端 Operation 目录/绑定状态页面，显示预注册 `knowledge-base.search` fake Operation；不允许客户端注册 Operation 或配置任意连接器。
- **M3：** 开放 Agent Skills 包导入/导出、租户 Connector 连接配置、多 Operation、健康检查、导入历史和高级审计筛选。

**Files:**
- Create: `web/admin/src/features/skills/pages/SkillImportPage.tsx`
- Create: `web/admin/src/features/skills/pages/SkillConnectorsPage.tsx`
- Create: `web/admin/src/features/skills/pages/SkillAuditPage.tsx`
- Create: `web/admin/src/features/skills/api/importApi.ts`
- Create: `web/admin/src/features/skills/api/connectorApi.ts`
- Create: `web/admin/src/features/skills/api/auditApi.ts`
- Create: `web/admin/src/features/skills/components/SkillImportPreview.tsx`
- Modify: `web/admin/src/features/skills/components/OperationSelector.tsx`
- Modify: `web/admin/src/features/skills/hooks/useSkillQueries.ts`
- Modify: `web/admin/src/features/skills/hooks/useSkillMutations.ts`
- Modify: `web/admin/src/styles/skills.css`
- Create: `web/admin/tests/t20_tool_skill_admin_playwright.py`

- [ ] **Step 1: Write failing API/helper tests for import preview and secret masking.**

  ```ts
  it('renders blocking package findings before the apply action', () => {
    expect(groupImportFindings({ blocking: [{ code: 'SCRIPT_FILE' }], warnings: [] })).toEqual({
      blocking: 1,
      warnings: 0,
    });
  });

  it('never formats a connector secret for display', () => {
    expect(formatConnection({ hasSecret: true, secret: 'enc:v2:...' } as never)).toEqual({
      hasSecret: true,
      secret: '••••••••',
    });
  });
  ```

- [ ] **Step 2: Run the tests and confirm pages/APIs are absent.**

  ```powershell
  cd web/admin
  npm test -- --run src/features/skills
  ```

  Expected: FAIL for missing import helpers and page modules.

- [ ] **Step 3: Implement the Import/Export page.**

  `SkillImportPage` is a four-panel workflow:

  1. **Select package:** accept one `.zip`, show file name/size/hash after the server preview, reject client-side obvious non-ZIP files, and never unzip in the browser.
  2. **Security scan:** render root/`SKILL.md` checks, size/member counts, blocked files/content findings, manifest summary, allowed references/assets, and package hash. Blocking findings disable “下一步”.
  3. **Mapping:** select active category, choose the server-listed Connector Operation, review candidate `metadata.lingxi` values as non-authoritative, and select role grants. Show no secret or internal endpoint values.
  4. **Conflict/apply:** if the key exists, require `CREATE_NEW`, `NEW_DRAFT_VERSION` with a selected target, or `CANCEL`; show exactly what will be created. “应用导入” creates a DRAFT only and links to the editor.

  Add an import history table with status (`PREVIEWED`, `APPLIED_DRAFT`, `REJECTED`, `CANCELED`), uploader/time/hash, finding count, and created Skill/version. Export action downloads the server response as a file; the page labels the export as metadata and safe resources only.

- [ ] **Step 4: Implement the Connector page.**

  `SkillConnectorsPage` is visible only with `SKILL_CONNECTOR_MANAGE`. Render connector cards with status, version, health, last check, and enabled operation count. Expand an operation to see display name, side-effect level, input/output contract, timeout/cancel/retry capabilities, and the Skills using it. The connection form allows only registered safe configuration fields and a secret input; after save show `hasSecret` and masked value, never the encrypted text. Health check shows safe success/failure code and request ID. Disable/enable requires confirmation and immediately invalidates operation and Skill validation queries.

- [ ] **Step 5: Implement the audit page.**

  `SkillAuditPage` queries `GET /skill-audit-events` with date range, event type, actor, Skill, version, execution status, and request ID filters. Render actor/tenant, event, resource, version, outcome, timestamp, and request ID. Detail drawer shows redacted before/after summary, role-code changes, safe input/result summary, and error code; it must not show raw input, result, credentials, URLs, SQL, package scripts, or storage keys. Add pagination and server-side filtering; do not export audit records as Skill packages.

- [ ] **Step 6: Run front-end checks and commit the operations pages.**

  ```powershell
  cd web/admin
  npm test -- --run src/features/skills
  npm run typecheck
  npm run lint
  npm run build
  ```

  Expected: PASS; importing, mapping, applying, exporting, configuring a connection, and viewing redacted audit data are available only behind their permission gates.

  ```powershell
  git add web/admin/src/features/skills/pages/SkillImportPage.tsx web/admin/src/features/skills/pages/SkillConnectorsPage.tsx web/admin/src/features/skills/pages/SkillAuditPage.tsx web/admin/src/features/skills/api/importApi.ts web/admin/src/features/skills/api/connectorApi.ts web/admin/src/features/skills/api/auditApi.ts web/admin/src/features/skills/components/SkillImportPreview.tsx web/admin/src/features/skills/components/OperationSelector.tsx web/admin/src/features/skills/hooks web/admin/src/styles/skills.css web/admin/tests/t20_tool_skill_admin_playwright.py
  git commit -m "feat: add skill import connector and audit pages"
  ```

### Task 13: Add the Chat Skills drawer, presets, structured form, and run card

**阶段切片：**

- **M1：** 完成分类浏览、可用 Skill 列表、手动选择、结构化参数表单、明确确认执行和固定 Demo Handler 结果卡；不提供收藏、显示名称、默认参数保存或排序。
- **M2：** 接入真实登录/租户上下文、`SKILL_READ`/`SKILL_EXECUTE` 过滤、fake Operation 的异步状态、超时、取消、审计和产物下载；不显示个人收藏或 Preset 控件。
- **M3：** 增加租户内用户私有 `SkillPreset`，实现收藏、默认参数、显示名称和排序；Preset 不能改变 Skill、版本、Operation、角色、URL、SQL、凭据或安全策略。

**Files:**
- Create: `web/admin/src/features/chat/api/skillApi.ts`
- Create: `web/admin/src/features/chat/hooks/useSkillStream.ts`
- Create: `web/admin/src/features/chat/components/SkillDrawer.tsx`
- Create: `web/admin/src/features/chat/components/SkillDetailPanel.tsx`
- Create: `web/admin/src/features/chat/components/SkillInputForm.tsx`
- Create: `web/admin/src/features/chat/components/SkillRunCard.tsx`
- Modify: `web/admin/src/features/chat/pages/ChatPage.tsx`
- Modify: `web/admin/src/features/chat/types.ts`
- Modify: `web/admin/src/features/chat/api/chatApi.ts`
- Modify: `web/admin/src/features/chat/components/ChatMessageList.tsx`
- Modify: `web/admin/src/styles/index.css`
- Modify: `web/admin/src/styles/skills.css`
- Create: `web/admin/tests/t21_tool_skill_chat_playwright.py`

- [ ] **Step 1: Write failing Chat UI and SSE parser tests.**

  Add pure tests for the user contract:

  ```ts
  it('renders only available published definitions returned by the server', () => {
    expect(filterAvailableSkills([{ status: 'PUBLISHED' }, { status: 'DRAFT' }])).toHaveLength(1);
  });

  it('submits only skillId and input', () => {
    expect(buildSkillRunBody('skill-1', { format: 'csv' })).toEqual({
      skillId: 'skill-1',
      input: { format: 'csv' },
    });
  });

  it('parses all Skill SSE events and preserves terminal status', () => {
    const state = reduceSkillEventSequence([
      { type: 'skill_run_started', data: { executionId: 'e1', version: 2 } },
      { type: 'skill_run_status', data: { executionId: 'e1', status: 'RUNNING', label: '运行中' } },
      { type: 'skill_run_result', data: { executionId: 'e1', summary: '完成' } },
      { type: 'skill_run_done', data: { executionId: 'e1', status: 'SUCCEEDED', durationMs: 120 } },
    ]);
    expect(state.status).toBe('SUCCEEDED');
    expect(state.executionId).toBe('e1');
  });

  it('does not render connector keys, roles, credentials, SQL, or URLs in a definition', () => {
    expect(sanitizeAvailableDefinition(untrustedDefinition)).not.toHaveProperty('connectorKey');
  });
  ```

- [ ] **Step 2: Run the tests and confirm the Chat Skill UI is absent.**

  ```powershell
  cd web/admin
  npm test -- --run src/features/chat
  ```

  Expected: FAIL with missing API, reducer, and component modules.

- [ ] **Step 3: Implement the staged Chat Skill API and typed state.**

  The common API exposes:

  ```ts
  getAvailableCategories(): Promise<SkillCategorySummary[]>;
  getAvailableSkills(categoryId?: string): Promise<SkillSummary[]>;
  getAvailableDefinition(skillId: string): Promise<SkillAvailableDefinition>;
  streamSkillRun(sessionId: string, body: { skillId: string; input: Record<string, unknown> }, handlers, options): Promise<void>;
  ```

  M1 calls local-demo endpoints and does not request preset/audit data. M2 relies on the server to filter by authenticated tenant, `SKILL_READ`, `SKILL_EXECUTE`, published version and role grant. M3 adds `getPreset(skillId)` and `savePreset(skillId, payload)`; those calls are user/tenant scoped. The request builder must create exactly `{ skillId, input }`; an `Idempotency-Key` may be sent as a header, but version IDs, Connector/Operation keys, role IDs, URL, SQL and credentials never enter the body.

- [ ] **Step 4: Implement the Skills drawer and details flow.**

  Add a “Skills” button beside the existing Chat composer. `SkillDrawer` contains:

  - active category tabs/list from the server;
  - search in M1/M2; add the “收藏” filter only in M3 after the private preset query is available;
  - available Skill cards with icon, name, description, category, favorite state, side-effect badge, and version;
  - loading/error/empty states that include the request ID when available;
  - no card for a Skill the server did not return.

  Clicking a card opens `SkillDetailPanel` with purpose, suitable scenarios, input/output description, limits, side-effect level, confirmation text, and current preset defaults. Keep the ordinary natural-language composer visible but separate; selecting a Skill must not put its fields into the free-text message box.

- [ ] **Step 5: Implement the schema-driven input form and private preset controls.**

  `SkillInputForm` renders only the server's restricted schema types and checks required/min/max/enum/date/file-reference constraints before enabling execution. It displays field help and safe default values. Unknown schema keywords render a blocking “无法渲染” state rather than falling back to a free-form JSON editor.

  In M3 only, provide “收藏”, custom display name, “保存为默认参数”, “恢复默认”, and display order actions through `SkillPreset`. Saving sends only `isFavorite`, `displayName`, `defaultInput`, and `displayOrder`, then validates against the current available definition. In M1/M2 these controls do not render; schema defaults are session-only. If the Skill is disabled or the published version changes, re-fetch the definition and revalidate defaults before allowing execution. No control enables creation, sharing, publishing, Operation changes, or role changes.

- [ ] **Step 6: Implement explicit confirmation and Skill run card.**

  Clicking “执行” opens a confirmation block when the policy requires it. The confirmation text includes Skill name, a concise input summary with sensitive fields masked, side-effect level, and the fact that the operation is controlled by the platform. Only after the user clicks the second “确认执行” does `streamSkillRun` start.

  `SkillRunCard` renders request summary, status labels, progress, elapsed time, safe result summary, bounded structured data, artifacts with download buttons, safe error/retryable state, cancel button while supported, and retry button only when the server says the policy permits it. It must show `PENDING`, `VALIDATING`, `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `TIMED_OUT`, `CANCELED`, and `REJECTED` distinctly. It must not display stack traces, storage keys, secret values, or raw connector diagnostics.

- [ ] **Step 7: Implement SSE state and reconnect behavior.**

  `useSkillStream` owns an `AbortController`, request ID, execution ID, event sequence, and terminal state. Parse `skill_run_started`, `skill_run_status`, `skill_run_progress`, `skill_run_result`, `skill_run_artifact`, `skill_run_error`, and `skill_run_done`. Ignore heartbeat comments and malformed frames without crashing. On disconnect, call `GET /skill-executions/{id}` to reconcile persisted events; do not blindly mark failure. Cancel invokes the cancel endpoint and waits for `skill_run_done`/status refresh. Retry creates a new card linked to the original execution.

- [ ] **Step 8: Integrate Chat message rendering and responsive styles.**

  Extend `ChatMessageList` to render `SKILL_REQUEST` and `SKILL_RESULT` with `SkillRunCard`; ordinary `TEXT` messages retain the existing rendering. Add mobile layout rules: drawer becomes a full-height sheet, form controls remain keyboard accessible, status cards wrap, and artifact actions remain visible at narrow widths. Add focus trapping/escape close for the drawer, labels for all controls, keyboard activation for cards, and visible non-color status indicators.

- [ ] **Step 9: Add browser acceptance coverage.**

  `t21_tool_skill_chat_playwright.py` must verify:

  1. An employee sees only categories/Skills returned by the authorized API.
  2. A draft, disabled, archived, or unauthorized Skill is not shown.
  3. The user opens a Skill, sees the structured form, saves a favorite/default, reloads, and sees the private preset.
  4. The browser request body contains only `skillId` and `input`.
  5. The user must click execute and then confirm for an external-write test Skill; ordinary Chat text never triggers a Skill.
  6. Status, progress, success/failure/timeout/cancel, safe result, and artifact cards render from SSE/mock API responses.
  7. A direct guessed Skill ID or forged version/operation field is rejected by the backend and the UI shows a safe error.

- [ ] **Step 10: Run front-end and browser tests, then commit.**

  ```powershell
  cd web/admin
  npm test -- --run src/features/chat
  npm run typecheck
  npm run lint
  npm run build
  cd ../..
  pytest web/admin/tests/t21_tool_skill_chat_playwright.py -q
  ```

  Expected: PASS; users manually choose and execute authorized Tool Skills in Chat, while private presets improve convenience without creating shared Skills.

  ```powershell
  git add web/admin/src/features/chat web/admin/src/styles/index.css web/admin/src/styles/skills.css web/admin/tests/t21_tool_skill_chat_playwright.py
  git commit -m "feat: add chat tool skill execution UI"
  ```

### Task 14: Complete integration, security, observability, and release acceptance

**阶段切片：**

- **M1 验收：** 只验证 loopback + local-demo flag + 固定 Demo Handler 的创建/编辑/发布/手动执行闭环；不把真实登录、租户隔离、`SKILL_READ`/`SKILL_EXECUTE`、fake Connector Operation、Preset 或生产部署写入 M1 通过条件。
- **M2 验收：** 在真实登录和租户上下文中验证 `SKILL_READ`/`SKILL_EXECUTE`、RBAC/角色授权、预注册 `knowledge-base.search` fake Operation、版本生命周期、超时/取消、审计、产物下载和越权拒绝。M2 是首个允许进入受控 staging/production 的版本。
- **M3 验收：** 在 M2 安全边界上验证收藏、默认参数、显示名称、排序、私有 `SkillPreset`、安全导入导出、多 Connector/Operation 和生产治理。

**Files:**
- Modify: `server/tests/e2e/test_tool_skill_e2e.py`
- Create: `server/tests/e2e/test_m1_tool_skill_closed_loop.py`
- Create: `server/tests/e2e/test_m2_tool_skill_operational_loop.py`
- Create: `server/tests/e2e/test_m3_tool_skill_complete.py`
- Modify: `pyproject.toml`
- Modify: `server/tests/security/test_skill_security.py`
- Create: `server/tests/test_skill_release_acceptance.py`
- Create: `docs/development/v1.1/skills/tool-skill-runbook.md`
- Create: `docs/development/v1.1/skills/tool-skill-acceptance-matrix.md`
- Modify: `web/admin/openapi.json`
- Modify: `web/admin/src/api/schema.d.ts`
- Modify: `web/admin/tests/t20_tool_skill_admin_playwright.py`
- Modify: `web/admin/tests/t21_tool_skill_chat_playwright.py`

- [ ] **Step 1: Write a phase-tagged release acceptance matrix as executable tests.**

  `test_skill_release_acceptance.py` must keep milestone boundaries visible in test names and cover at least:

  | Area | M1 local-demo assertion | M2 secure-operations assertion | M3 production/personalization assertion |
  |---|---|---|---|
  | Admin create | Demo admin creates category and Tool Skill draft through loopback gate. | Authenticated admin creates a tenant-scoped draft with `SKILL_MANAGE`. | Imported package maps into a new draft only. |
  | Schema | Invalid root/additional property/runtime field is rejected. | Schema is intersected with the selected fake Operation contract. | Imported references/assets are normalized and scanned. |
  | Binding | Fixed `customer_report_search` handler only. | Only pre-registered `knowledge-base.search` is selectable; client cannot choose a key. | Additional Operations remain server-registry controlled. |
  | Publish | Valid metadata/schema can be published in local namespace. | Operation, active category, role grant, policy, tenant and audit are required. | Import never auto-publishes and health warnings are enforced. |
  | Auth/RBAC | Local-demo identity and loopback gate; no real permission claim. | Login/session, tenant isolation, `SKILL_READ`, `SKILL_EXECUTE`, management permissions and role grants are enforced server-side. | Preset and governance APIs preserve the same tenant/role rules. |
  | Version/lifecycle | Single demo draft/published pointer; no version history claim. | Published edit creates an immutable draft/version; disable/archive blocks new runs but preserves history. | Import/export and Connector lifecycle retain provenance and audit. |
  | Execution | Explicit Chat click invokes only the inline Demo Handler. | Input, tenant, role, Operation, connection, audit and idempotency checks happen before Celery invocation. | Retry/rate/concurrency/health/retention policies hold. |
  | Chat | Category browse → manual select → form → confirm → bounded result. | Authorized user sees progress, timeout, cancel, safe result and artifact download. | User can privately save favorite, display name, default input and order. |
  | Security | Non-loopback, disabled flag, arbitrary handler and runtime-control injection are rejected. | Cross-tenant, unauthenticated, missing permission, forged version/Operation/role and artifact-download attempts are rejected. | Malicious packages, scripts, secrets, SSRF/free SQL and unsafe Connector config are rejected. |

- [ ] **Step 2: Add phase-scoped malicious-input and resource-exhaustion security tests.**

  `server/tests/security/test_skill_security.py` must include:

  - **M1:** non-loopback requests, disabled local-demo flag, forged `connectorKey`/`operationKey`/`roleIds`/URL/SQL/credential fields, unknown schema fields and oversized input. Every rejection must be a safe public error with zero Demo Handler calls; the fixed Handler cannot access network, SQL, files or credentials.
  - **M2:** unauthenticated/expired sessions, cross-tenant IDs, missing `SKILL_READ`, missing `SKILL_EXECUTE`, missing role grant, inactive category/Skill/Operation/connection, forged version/Operation/role fields, audit-write/queue failures, timeout/cancel races, sensitive output, result-size limits and artifact download replay.
  - **M3:** ZIP path traversal, absolute path, duplicate entry, symlink, encrypted archive, compression bomb, member-count and size limits; scripts/executables; private-key/bearer/cloud/database-secret patterns; internal HTTP SSRF; free SQL/comment/union injection; unsafe Connector configuration; and rate/concurrency/retention tests.

  All phases must assert a safe public error. M2/M3 tests must additionally assert no Connector call, no package execution and no secret/traceback in normal logs or audit exports.

- [ ] **Step 3: Add separate end-to-end admin-to-Chat coverage for each milestone.**

  `server/tests/e2e/test_m1_tool_skill_closed_loop.py` runs against a loopback test app with local-demo mode enabled:

  1. Demo admin creates a category and `customer-report-search` with `query`/`limit` schema.
  2. Admin validates, fixes a bad schema, publishes the Skill and sees it in the local availability endpoint.
  3. Demo Chat user manually selects it, submits `{skillId, input}`, receives ordered started/status/result/done events and a safe result.
  4. Non-loopback requests, ordinary natural-language text and injected runtime fields are rejected.

  `server/tests/e2e/test_m2_tool_skill_operational_loop.py` runs against temporary tenants:

  1. Seed real users/roles/permissions and the `knowledge-base.search` fake Operation with a safe test connection.
  2. Authenticated admin creates a tenant-scoped Skill, binds the fake Operation, grants a role, validates and publishes version 1.
  3. Authorized user lists/executes it; missing `SKILL_READ`/`SKILL_EXECUTE`, unauthorized role and cross-tenant user are rejected.
  4. Admin publishes version 2; history remains pinned to version 1; disable/archive blocks new runs.
  5. A long fake run demonstrates queue/progress/timeout/cancel, audit events and authorized artifact download.

  `server/tests/e2e/test_m3_tool_skill_complete.py` additionally verifies private favorite/display-name/default/order isolation, import-to-draft-only behavior, malicious package rejection and Connector health/configuration gates.

- [ ] **Step 4: Verify OpenAPI and generated front-end types.**

  Start the API with the test configuration, fetch the OpenAPI document, and regenerate the existing front-end type file:

  ```powershell
  python -m uvicorn server.app.main:app --host 127.0.0.1 --port 8000
  curl http://127.0.0.1:8000/openapi.json -o web/admin/openapi.json
  cd web/admin
  npm run gen:api
  npm run typecheck
  ```

  Expected: the new endpoints, aliases, error shapes, SSE request schemas, and permission-protected resources are present; no schema exposes encrypted secrets or internal connector endpoints. Stop the temporary server after generation.

- [ ] **Step 5: Add runbook and operational dashboards.**

  `tool-skill-runbook.md` must document migrations, seed upgrade, worker queues, configuration ceilings, connector health checks, secret rotation, package rejection handling, cancel/timeout behavior, artifact cleanup, audit retention, disable switch, rollback procedure, and incident response. It must state that an imported package is never executable and that `SKILL_MANAGE` is not granted to Chat users.

  Add metrics/log fields without secrets: execution count/status/duration by Skill/version/operation, queue latency, validation rejection code, connector health, timeout/cancel count, artifact bytes, import scan rejection code, and audit-write failure. Ensure ordinary Chat dashboards still work when a Skill connector is down.

- [ ] **Step 6: Run the complete verification suite.**

  From `D:\codeproject\python\lingxi`:

  ```powershell
  pytest server/tests/test_skill_contracts.py server/tests/test_skill_models.py server/tests/test_skill_permissions.py server/tests/test_skill_connectors.py server/tests/test_skill_operations.py server/tests/test_skills_api.py server/tests/test_skill_import.py server/tests/test_skill_preset.py server/tests/test_skill_execution.py server/tests/test_skill_sse.py server/tests/test_skill_chat_api.py server/tests/security/test_skill_security.py server/tests/e2e/test_tool_skill_e2e.py server/tests/test_skill_release_acceptance.py -q
  cd web/admin
  npm test
  npm run typecheck
  npm run lint
  npm run build
  cd ../..
  pytest web/admin/tests/t20_tool_skill_admin_playwright.py web/admin/tests/t21_tool_skill_chat_playwright.py -q
  git diff --check
  ```

  Expected: all focused/backend/security/browser checks pass; migration reaches head; no diff whitespace errors; ordinary existing tests are then run with `pytest server/tests -q` and the full Playwright release set.

- [ ] **Step 7: Commit the release verification and documentation.**

  ```powershell
  git add server/tests/e2e/test_tool_skill_e2e.py server/tests/security/test_skill_security.py server/tests/test_skill_release_acceptance.py docs/development/v1.1/skills web/admin/openapi.json web/admin/src/api/schema.d.ts web/admin/tests/t20_tool_skill_admin_playwright.py web/admin/tests/t21_tool_skill_chat_playwright.py
  git commit -m "test: complete tool skill release acceptance"
  ```

## 最终实施检查清单

以下检查在每个里程碑退出时都执行；M1/M2/M3 的具体命令和人工脚本见上文，Task 14 负责把它们汇总为发布验收记录。

- [ ] 占位符扫描没有发现未替换的占位符标记、示例路径或示例 ID。
- [ ] 所有设计实体已映射到 ORM、迁移、repository、service、API 和测试；M1/M2/M3 的任务切片没有引用不存在的字段或旧 API 名称。
- [ ] 七类 Skill SSE 事件（started、status、progress、result、artifact、error、done）按里程碑逐步实现：M1 至少有 started/status/result/done，M2 补齐 progress/artifact/error 和重连，M3 复用同一契约。
- [ ] 所有用户侧/管理侧 API、后台页面和 Chat 页面都映射到对应 Task；浏览器验收不会依赖手工修改数据库。
- [ ] 包扫描、SSRF、自由 SQL、凭据泄露、跨租户访问、资源耗尽和下载越权均有命名控制与自动化测试，并按 M2/M3 里程碑启用。
- [ ] 所有权限和授权公式都由服务端执行；前端过滤只用于体验。M1 的例外仅是显式 loopback local-demo gate，不得被描述为真实权限。
- [ ] Skill 和 SkillExecution 状态机均有合法/非法转换测试；终态不可被晚到的 worker 结果覆盖。
- [ ] `POST /chat/sessions/{session_id}/skill-runs` 的客户端请求体始终只包含 `skillId` 和结构化 `input`；服务端拒绝 version/connector/operation/role/URL/SQL/credential 注入。
- [ ] M1 只允许 local-demo 身份在 loopback 上创建/编辑/发布和手动执行固定 Demo Handler；不实现真实登录、租户隔离、`SKILL_READ`、`SKILL_EXECUTE`、fake Connector Operation、收藏、默认参数、显示名称、排序或 `SkillPreset`，且不得部署到共享 staging/production。
- [ ] M2 完成基础登录、会话过期、租户隔离、`SKILL_READ` / `SKILL_EXECUTE`、RBAC/角色授权、预注册 fake Connector Operation、版本、归档、超时、取消、审计和产物下载；每一项都有自动化测试和人工操作证据。M2 是首个可进入受控 staging/production 的里程碑。
- [ ] M3 完成用户私有 `SkillPreset` 的收藏、默认参数、显示名称和排序，并完成安全包导入/导出、Connector 运营、多 Operation、健康检查、重试/限流/并发和结果治理；Preset 不得创建或共享真正的 Skill。
- [ ] 任何执行都锁定租户、已发布版本、Operation 契约和角色快照；跨租户、未授权、停用、归档、连接器不可用和审计写入失败均 fail closed。
- [ ] M3 的包导入在解压前完成安全预检，永不执行包内脚本；Connector 和 Operation 只能由服务端白名单注册。
- [ ] `git diff --check`、后端 focused suite、前端 typecheck/lint/build、对应 marker 的 Playwright 和迁移 upgrade/downgrade 均通过。
- [ ] 完成 M3 后另行立项 Prompt Skill；本计划不把 Prompt Skill、模型自动选择、自治编排或共享用户 Skill 混入 Tool Skill 发布。

## 执行方式选择

计划已按三个可独立验收的里程碑拆分。实现阶段推荐使用 `subagent-driven-development`：每个 Task 由独立 worker 完成，主线程在任务之间审查 diff 和测试结果；如果希望在同一会话中连续实施，也可以使用 `executing-plans`，按 M1/M2/M3 的 gate 分批执行，不能跳过里程碑验收。
