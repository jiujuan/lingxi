# Tool Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax (- [ ]) for tracking.

**Goal:** 在灵犀第一期交付一个安全、可审计、按角色授权的 Tool Skill 系统：管理员可以创建、导入、配置、测试、发布和停用系统 Tool Skill，Chat 用户可以按分类手动选择并执行自己有权限的 Skill，并可以收藏 Skill、保存个人默认参数，但不能创建或共享真正的 Tool Skill。

**Architecture:** Skill 只保存面向用户的能力定义和不可变版本，不携带可执行代码；实际动作只能通过服务端注册、审核和配置的 Connector Operation 完成。后端以 SkillExecution 锁定发布版本、角色快照和操作契约，以 Celery 执行长任务并将脱敏事件写入数据库，Chat 通过既有 SSE 传输显示状态与结果。用户个性化能力使用租户内用户私有的 SkillPreset，它只能引用当前已发布的系统 Skill，不能改变连接器、Operation、权限、URL、SQL、凭据或安全策略。

**Tech Stack:** FastAPI、Pydantic、SQLAlchemy、Alembic、PostgreSQL/SQLite、Celery/Redis、jsonschema、PyYAML、React 19、TypeScript、Vite、TanStack Query、既有 Chat SSE 与 RBAC。

---

## 0. 第一期开工边界与不可违反的安全约束

本计划以 docs/superpowers/specs/2026-08-19-skills-management-system-design.md 为产品和接口基线。实现时必须同时满足以下范围：

1. skill_type 数据库保留 TOOL、PROMPT 两个枚举值，但第一期所有创建、导入、编辑和发布 API 只接受 TOOL。
2. 只有拥有 SKILL_MANAGE 的管理员可以创建/编辑系统 Skill；Chat 用户没有创建 Skill 的 API、页面或权限。
3. Chat 用户只能选择管理员发布且按角色授权的系统 Skill；第一期调用方式固定为“打开 Skills 面板 → 选择分类和 Skill → 填写结构化参数 → 明确点击执行”。模型不得自动选择或自动调用 Skill。
4. 用户私有 SkillPreset 可以保存显示名称、收藏状态、排序和默认参数；它不是 Skill 版本，不可共享，不可发布，不可绑定新 Connector Operation。
5. 任何执行都从服务端当前发布版本重新解析 connector_operation_id、角色授权和租户连接配置；客户端不得传 skill_version_id、connector_key、operation_key、角色、完整 URL、SQL 或凭据。
6. 导入包只作为草稿来源。导入预检拒绝脚本、可执行文件、路径穿越、符号链接、密钥模式、未知二进制、超大文件和压缩炸弹；系统永不加载或运行包内 scripts/。
7. 权限、审计写入、Connector 状态、凭据引用、输入校验任一失败时必须 fail closed，不得降级成未审计调用。


## 里程碑交付策略

本计划不再把 Task 1–14 视为一次性大版本，而是把它们切成三个能够独立部署、独立回归、独立人工演示的交付里程碑。每个里程碑都必须满足“自动化测试通过 + 浏览器人工验收通过 + 数据迁移可升级/回滚 + 安全边界没有被绕过”四个条件，才允许进入下一个里程碑。

### 共同交付约束

1. **每个里程碑都有可运行的闭环。** 里程碑一不是只交付模型或 API，而是必须完成“管理员创建/编辑/发布 → Chat 用户浏览/选择/填写/执行 → 返回安全结果”的完整路径。里程碑二在同一条路径上增加版本、生命周期、长任务、授权和审计；里程碑三再补齐导入、连接器运营和生产治理。
2. **数据库先保证向后兼容。** `0009_tool_skills.py` 在里程碑一创建 Skill、版本、角色授权、执行、事件、产物、Preset 和导入所需的基础表；里程碑二和三只添加索引、约束、字段和数据回填，不重命名里程碑一已经使用的列，不改变 `POST /chat/sessions/{session_id}/skill-runs` 的请求体语义。
3. **执行入口保持同一个服务接口。** 里程碑一使用 `InlineSkillExecutionDriver` 执行确定性的短任务；里程碑二切换到 `CelerySkillExecutionDriver`，但两者都调用同一个 `SkillExecutionService`，都先锁定服务端发布版本、Operation、租户连接和角色快照。这样里程碑一的 Chat UI 不需要在里程碑二重写。
4. **里程碑一也不能绕过安全门禁。** 里程碑一使用种子数据中的固定演示角色（`EMPLOYEE`）进行真实的 `SKILL_READ`、`SKILL_EXECUTE` 检查，管理员创建的演示 Skill 只允许授予该角色；不在 UI 暴露任意角色选择。里程碑二把固定角色策略替换为可配置的角色授权矩阵和管理员授权界面。
5. **功能开关只控制入口，不改变安全逻辑。** 使用以下配置键，默认值由部署环境显式设置：

   | 配置键 | 里程碑一 | 里程碑二 | 里程碑三 |
   |---|---|---|---|
   | `SKILLS_M1_CORE_ENABLED` | `true` | `true` | `true` |
   | `SKILLS_M2_OPERATIONS_ENABLED` | `false` | `true` | `true` |
   | `SKILLS_M3_IMPORTS_ENABLED` | `false` | `false` | `true` |
   | `SKILLS_EXECUTION_DRIVER` | `inline` | `celery` | `celery` |
   | `SKILLS_FIXED_DEMO_ROLE_MODE` | `true` | `false` | `false` |

   关闭开关时，服务端返回既有统一的 `FEATURE_DISABLED` 错误；不能仅仅隐藏前端按钮后仍允许直接调用 API。
6. **每个里程碑单独拥有验收测试入口。** 新增三个服务端验收文件，并在已有浏览器验收文件中按 marker 分组：

   - `server/tests/e2e/test_m1_tool_skill_closed_loop.py`
   - `server/tests/e2e/test_m2_tool_skill_operational_loop.py`
   - `server/tests/e2e/test_m3_tool_skill_complete.py`
   - `web/admin/tests/t20_tool_skill_admin_playwright.py` 中的 `@pytest.mark.m1`、`@pytest.mark.m2`、`@pytest.mark.m3`
   - `web/admin/tests/t21_tool_skill_chat_playwright.py` 中的 `@pytest.mark.m1`、`@pytest.mark.m2`、`@pytest.mark.m3`

7. **里程碑之间使用独立提交和验收标签。** 每个里程碑的最后一个提交必须只包含该里程碑计划范围内的代码、迁移、测试和文档。推荐标签分别为 `tool-skills-m1-closed-loop`、`tool-skills-m2-secure-operations`、`tool-skills-m3-production-complete`；标签建立前必须完成本文对应的退出条件。

---

## Milestone 1：Tool Skill 最小可用闭环

**目标：** 交付一个管理员能够在后台创建、编辑、校验和发布，Chat 用户能够按分类手动选择并执行的 Tool Skill 闭环。第一条演示链路使用服务端预注册的确定性 Operation，确保开发、测试和人工验收不依赖外部系统。

**交付结果：** 管理员登录 Skills 后台创建“客户报表查询”分类和 `customer-report-search` Tool Skill，绑定预注册的 `knowledge-base.search` fake Operation，发布后，员工在 Chat 的 Skills 面板中看到该 Skill，填写关键词并明确点击“执行”，页面显示结构化结果。用户可以收藏 Skill 和保存个人默认参数，但不能创建、发布、导入或共享真正的 Skill。

### M1 功能范围

| 领域 | 里程碑一交付内容 | 明确不在 M1 的内容 |
|---|---|---|
| Skill 合同 | TOOL 类型、`SKILL.md` 元数据映射、受限 JSON Schema、表单展示配置、执行策略上限 | PROMPT Skill、模型自动选择、自由脚本 |
| 持久化 | 分类、Skill、初始草稿版本、发布指针、执行记录、最小事件记录、私有 Preset | 版本历史页面、版本对比和回滚操作 |
| 管理后台 | Skills 列表、分类 CRUD、Tool Skill 编辑器、保存草稿、服务端校验、发布 | 导入/导出、连接器管理、完整角色授权矩阵、审计查询 |
| Connector | 服务端代码注册的 `knowledge-base.search` fake Operation；管理员只能从白名单选择 | 任意 URL、自由 SQL、用户上传代码、多 Connector 管理 |
| 执行引擎 | 同一执行服务接口下的 inline 短任务、输入校验、租户隔离、固定演示角色检查、结果脱敏、结果大小上限 | Celery 长任务、超时、取消、重试、产物下载、限流/并发控制 |
| Chat | 分类浏览、可用 Skill 列表、结构化参数表单、手动确认执行、结果卡片 | 自动触发、长任务进度、取消按钮、产物卡片 |
| 用户个性化 | 私有收藏、显示名称、排序、默认参数；严格限制为已发布系统 Skill 的引用 | 用户创建/发布/共享真实 Skill；改变 Operation、角色或策略 |
| 安全基线 | 登录、租户隔离、最小权限、固定角色真实授权检查、请求字段白名单、最小事件记录 | 可配置 RBAC 管理、完整审计检索和安全报表 |

### M1 技术切片和任务映射

1. **合同与迁移：Task 1、Task 2。** 先落地 `ToolInputSchema`、`SkillVersionDraftRequest`、`SkillAvailableDefinition` 和 `SkillRunCreateRequest`，再执行 `0009_tool_skills.py`。M1 只使用 `version_number=1` 的草稿/发布版本，但保留不可变版本字段、`current_published_version_id` 和角色授权表，保证 M2 可以直接增加版本历史，不需要重建数据。
2. **权限种子：Task 3 的 M1 slice。** 保留 `SKILL_READ`、`SKILL_EXECUTE`、`SKILL_MANAGE`、`SKILL_CATEGORY_MANAGE`；`SYSTEM_ADMIN` 拥有管理权限，`EMPLOYEE` 只拥有读取/执行权限。`SKILL_CONNECTOR_MANAGE` 和 `SKILL_AUDIT_READ` 可以提前种子化，但 M1 不开放对应页面。发布时服务端只允许给 `EMPLOYEE` 演示角色建立固定 grant，客户端不能提交任意 `roleIds`。
3. **受控 Operation：Task 4 的 M1 slice。** 只实现 `knowledge-base.search` 的 fake 注册项。它接受 `{ "query": string, "limit": integer }`，返回固定格式的本地测试结果和 `isArtifact=false`，不读取真实网络、不执行 SQL、不读取凭据。Operation 注册表仍然只允许服务端注册，Skill 编辑器只显示注册表中的安全展示名。
4. **管理域：Task 5 的 M1 slice。** 实现分类新增/编辑/停用、Skill 新建、草稿元数据编辑、输入 Schema 编辑、Operation 绑定、服务端校验和首次发布。已发布 Skill 的再次编辑只能创建/更新当前编辑草稿，不提供历史版本、回滚和归档按钮；旧的发布指针不会被客户端直接修改。
5. **私有 Preset：Task 7。** 在主闭环中实现收藏和默认参数保存。默认参数必须再次按当前发布版本的 Schema 校验，查询必须同时按 `tenant_id` 和 `user_id` 过滤；Preset 不存 connector、operation、role、URL、SQL、凭据或执行策略。
6. **执行引擎：Task 8 的 M1 slice。** 实现 `InlineSkillExecutionDriver` 和统一的 `SkillExecutionService`。流程为“鉴权 → 查当前发布版本 → 校验输入 → 创建执行 → 写入 started 事件 → 调用 fake Operation → 脱敏结果 → 写入 done/result 事件 → 返回 SSE 事件序列”。事件至少包含 `skill_run_started`、`skill_run_status`、`skill_run_result`、`skill_run_done`；没有队列时也必须持久化执行记录和请求 ID。
7. **Chat 后端：Task 9 的 M1 slice。** 实现可用分类、可用 Skill 定义和 `POST /chat/sessions/{session_id}/skill-runs`。M1 在 inline driver 下快速发完同一条 SSE 流；若前端环境不支持流式测试，允许通过 `GET /skill-executions/{execution_id}` 查询同一份结果。请求体只允许 `skillId` 和 `input`。
8. **管理后台：Task 10、Task 11 的 M1 slice。** 先完成列表和分类管理，再完成三步编辑器：基本信息 → Operation/参数 Schema → 校验/发布。编辑器必须显示 Skill 类型为 TOOL、当前状态、阻断错误和发布确认；不能渲染或接受 Connector 内部 URL、密钥、自由 SQL、脚本或任意角色 ID。
9. **Chat UI：Task 13 的 M1 slice。** 在 Skills 抽屉中按分类展示可用 Skill；进入详情后展示描述、输入限制和结构化表单；执行按钮必须是用户明确点击，不能由普通 Chat 文本触发。执行完成后显示安全结果、失败码和 request ID；收藏/默认参数保存后刷新页面仍然存在。
10. **M1 集成验收：Task 14 的 M1 slice。** 只运行 M1 acceptance matrix，确认 admin 和 employee 两个角色均经过真实权限中间件，且对伪造 `skillVersionId`、`connectorKey`、`operationKey`、`roleIds`、`url`、`sql`、`credential` 的请求返回 4xx 且 fake Operation 调用次数为 0。

### M1 自动化验证

从 `D:\codeproject\python\lingxi` 执行：

```powershell
$env:SKILLS_M1_CORE_ENABLED = "true"
$env:SKILLS_M2_OPERATIONS_ENABLED = "false"
$env:SKILLS_M3_IMPORTS_ENABLED = "false"
$env:SKILLS_EXECUTION_DRIVER = "inline"
$env:SKILLS_FIXED_DEMO_ROLE_MODE = "true"

pytest server/tests/test_skill_contracts.py -q
pytest server/tests/test_skill_models.py -m m1 -q
pytest server/tests/test_skill_permissions.py -m m1 -q
pytest server/tests/test_skill_connectors.py -m m1 -q
pytest server/tests/test_skill_operations.py -m m1 -q
pytest server/tests/test_skills_api.py -m m1 -q
pytest server/tests/test_skill_preset.py -m m1 -q
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

**M1 自动化通过标准：** 共享测试文件中的 M1 用例必须标注 `@pytest.mark.m1`，未标记的基础合同测试单独运行；后端 focused suite、M1 e2e、前端单元/类型/构建和两个浏览器 marker 全部 PASS；`test_m1_tool_skill_closed_loop.py` 至少验证管理员创建/发布、员工可见/可执行、结果事件顺序、用户不能管理、跨租户不可见和伪造控制字段拒绝。

### M1 人工验收脚本

使用一套本地演示租户，准备两个账号：`system_admin` 和 `employee`。测试数据只包含本地 fake Operation，禁止把真实生产连接器作为 M1 的验收依赖。

1. **管理员进入 Skills。** 登录管理后台，确认左侧出现“Skills”；`employee` 登录后不显示管理入口，直接访问管理 URL 返回 403/统一无权限页。
2. **创建分类。** `system_admin` 打开“分类管理”，新增“客户数据”，填写 key `customer-data`、名称和描述，保存后在列表中看到“启用”。编辑名称并刷新，确认修改持久化。
3. **创建 Skill 草稿。** 打开“Skills 列表”→“新建 Tool Skill”，填写 key `customer-report-search`、名称“客户报表查询”、描述、分类，确认类型固定显示 TOOL 且不可切换为 PROMPT。
4. **绑定安全 Operation。** 在编辑器的 Operation 下拉框选择 `knowledge-base.search`；确认列表不出现 URL、SQL、凭据输入框，也不能粘贴或保存未知 operation key。
5. **配置输入表单。** 在参数 Schema 步骤添加必填 `query` 字符串和可选 `limit` 整数，设置默认值 `10`；尝试添加 `password`、`url` 或 `sql` 字段，页面显示阻断校验并且保存请求被服务端拒绝。
6. **保存并发布。** 点击“保存草稿”，返回列表确认状态为“草稿”；点击“校验”，确认无阻断错误；点击“发布”并确认弹窗，列表状态变为“已发布”。刷新后 Skill 仍然存在。
7. **Chat 浏览和手动选择。** 用 `employee` 打开 Chat → Skills，按“客户数据”分类看到“客户报表查询”；打开详情看到描述和 `query`/`limit` 表单。普通 Chat 输入“请自动调用客户报表查询”不会创建 Skill 执行。
8. **收藏和默认参数。** 点击收藏，设置默认 `limit=10`，刷新浏览器并重新打开 Skill，确认收藏状态和默认值保留；确认只能影响当前 employee，不影响另一个账号。
9. **执行并查看结果。** 填写 `query=华东客户`，点击“执行”并确认，看到 started/status/result/done 对应的运行卡片和 fake Operation 返回的结构化结果。页面显示 request ID，但不显示内部连接器地址、凭据、堆栈或原始日志。
10. **安全负向操作。** 使用浏览器开发者工具手工把请求体增加 `skillVersionId`、`connectorKey`、`operationKey` 或 `roleIds`，服务端返回 400/422；把 `skillId` 改成未授权或另一租户的 ID，返回 403/404；后端 fake Operation 记录没有新增调用。

### M1 退出条件和演示包

- [ ] `0009_tool_skills.py` 在空数据库和现有开发数据库上都能升级，既有业务测试无回归。
- [ ] 管理员创建/编辑/发布和 Chat 浏览/选择/执行的闭环可在本地一键启动后完成。
- [ ] M1 的所有自动化命令通过，且没有被 `xfail`、跳过或仅依赖人工判断的关键断言。
- [ ] 人工验收脚本 1–10 全部通过并保存截图/录屏到 `docs/development/v1.1/acceptance/tool-skills/m1/`。
- [ ] 现有系统中不存在 Chat 用户创建、导入、发布或共享真实 Skill 的 UI/API。
- [ ] M1 发布标签建立后，才允许开始 M2 的长任务、授权矩阵和生命周期开发。

**M1 可演示结果：** 一名管理员从空白分类开始创建一个 Tool Skill，一名员工在 Chat 中按分类手动选择它，填写结构化参数并得到结果；这个结果可重复、可自动化测试，并且客户端无法注入 Operation、角色或凭据。

---

## Milestone 2：可安全运营的 Tool Skill 执行闭环

**目标：** 在 M1 的可用闭环上补齐版本、生命周期、长任务控制、审计、产物下载和完整 RBAC/角色授权，使 Tool Skill 可以在受控生产环境中运营。

**交付结果：** 管理员可以从已发布版本创建新草稿、查看版本差异、发布或回滚形成的新版本、停用/归档 Skill，并为不同角色授权；Chat 用户只能看到并执行自己被授权的已发布 Skill。长任务能够显示状态和进度，用户可以取消；执行超时、审计写入失败、权限不匹配和产物越权下载都能安全失败。

### M2 功能范围

| 领域 | 里程碑二交付内容 | M2 仍不包含的内容 |
|---|---|---|
| 版本 | 不可变版本、版本列表、差异、发布、回滚为新版本、执行锁定版本 | Prompt Skill 的版本与模型策略 |
| 生命周期 | 禁用、重新启用、归档（归档为终态）；保留历史执行 | 删除历史、物理清理执行数据 |
| RBAC | Skill 管理/读取/执行/分类/连接器/审计权限；按租户和角色授权；授权变更审计 | Chat 用户创建共享 Skill |
| 执行 | Celery/Redis 队列、状态机、超时、取消、幂等、并发和输出基础限制 | 高级重试策略、跨 Skill 编排 |
| 审计 | 管理、授权、执行、取消、超时、下载事件的脱敏记录和查询页面 | SIEM/SOC 外部联动 |
| 产物 | 白名单产物存储、二次鉴权、短时下载令牌、过期清理 | 任意文件浏览或任意路径下载 |
| 管理后台 | 版本历史/差异、发布/回滚/停用/归档确认、角色授权、审计查询 | 包导入、连接器连接配置、健康检查页面 |
| Chat | 运行中状态、进度、取消、终态、错误、产物下载 | 自动重试和复杂工作流 |

### M2 技术切片和任务映射

1. **权限和授权矩阵：Task 3、Task 5 的 M2 slice。** 开启 `SKILLS_M2_OPERATIONS_ENABLED` 后，移除 M1 的固定演示角色限制，管理员可以在 Skill 版本授权面板选择当前租户角色。服务端使用 `user_has_permission(SKILL_EXECUTE) AND active_skill AND active_category AND published_version AND role_grant AND active_operation AND active_connection` 公式；任一条件失败都返回安全错误。角色 ID、权限和租户 ID 始终由服务端解析。
2. **版本和生命周期：Task 5 的 M2 slice。** 编辑已发布版本时创建新的不可变草稿；发布后旧版本仍可被历史执行引用但不再用于新执行。版本差异只返回脱敏字段；回滚不是修改旧版本，而是复制目标版本内容创建新的草稿并重新校验。归档是终态，停用阻止新执行但保留列表和执行历史。
3. **异步执行：Task 8 的 M2 slice。** 用 `CelerySkillExecutionDriver` 替换 inline driver，使用同一 `SkillExecutionService`。实现 `PENDING → VALIDATING → QUEUED → RUNNING → SUCCEEDED/FAILED/TIMED_OUT/CANCELED`，每个状态转换写入事件；队列提交失败不得伪造成功。
4. **超时和取消：Task 8 的 M2 slice。** 在 Operation 契约和 Skill execution policy 的较小者上设置超时；取消只向声明支持取消的 Operation 发送 cancel token，不支持时标记取消请求并等待安全终止。超时和取消必须阻止后续成功结果覆盖终态。
5. **审计：Task 8、Task 12 的 M2 slice。** `skill_audit_service.py` 写入发布、停用、归档、授权变更、执行、取消、超时、下载和失败事件；输入、结果、凭据、连接器内部地址和 traceback 均按 schema 进行脱敏。审计写入失败时，管理变更和执行创建均 fail closed；审计查询只能看到本租户允许的字段。
6. **产物：Task 8、Task 9 的 M2 slice。** 只允许注册 Operation 通过 `SkillArtifactService` 写入白名单目录/对象存储；下载端点再次检查租户、执行所有者、角色和产物未过期状态，并签发短时令牌。令牌一次性使用或在有效期内绑定用户/租户，不能通过修改 artifact ID 下载他人文件。
7. **后台 UI：Task 10、Task 11、Task 12 的 M2 slice。** 列表新增版本、授权角色、最近运行状态；编辑器新增版本历史和 JSON/表单差异；发布、回滚、停用、归档、授权变更均使用明确确认弹窗；新增审计页，支持按 Skill、操作者、事件、状态和时间范围筛选。
8. **Chat UI：Task 13 的 M2 slice。** 运行卡片显示排队、执行、进度、失败、超时、取消；长任务提供取消按钮和防重复点击；成功后显示产物文件名、大小和下载按钮；下载失败显示安全错误而不暴露存储 key。
9. **M2 集成验收：Task 14 的 M2 slice。** 增加跨角色、跨租户、版本锁定、生命周期、审计失败、超时/取消竞态、产物越权、幂等和状态机测试。

### M2 自动化验证

```powershell
$env:SKILLS_M1_CORE_ENABLED = "true"
$env:SKILLS_M2_OPERATIONS_ENABLED = "true"
$env:SKILLS_M3_IMPORTS_ENABLED = "false"
$env:SKILLS_EXECUTION_DRIVER = "celery"
$env:SKILLS_FIXED_DEMO_ROLE_MODE = "false"

pytest server/tests/test_skill_permissions.py -m "m1 or m2" -q
pytest server/tests/test_skills_api.py -m "m1 or m2" -q
pytest server/tests/test_skill_execution.py -m "m1 or m2" -q
pytest server/tests/test_skill_sse.py -m "m1 or m2" -q
pytest server/tests/test_skill_chat_api.py -m "m1 or m2" -q
pytest server/tests/test_skill_release_acceptance.py -m "m1 or m2" -q
pytest server/tests/e2e/test_m1_tool_skill_closed_loop.py -q
pytest server/tests/e2e/test_m2_tool_skill_operational_loop.py -q
pytest server/tests/security/test_skill_security.py -m "m1 or m2" -q

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

**M2 自动化通过标准：** 共享测试文件中的 M1/M2 用例必须分别标注 marker，M2 命令只运行 `m1 or m2`；M1 全部测试继续通过；M2 测试覆盖版本、角色授权、状态机、超时、取消、审计、产物下载和越权拒绝；Playwright 能稳定等待队列状态，不依赖固定 sleep；同一 `idempotency-key` 不会创建重复执行。

### M2 人工验收脚本

使用 M1 已发布的 `customer-report-search`，再准备一个由 fake Connector 模拟 8 秒延迟和可取消能力的 `customer-report-export` Skill。创建 `system_admin`、`report_viewer`、`report_operator` 三个角色，并分别准备有/无授权的用户。

1. **创建新版本。** 管理员打开已发布 `customer-report-search`，修改表单字段描述或默认 `limit`，保存后确认产生“草稿 v2”；版本列表中 v1 仍显示“已发布”，v1 的内容和内容 hash 不变。
2. **查看差异并发布。** 打开 v1/v2 差异，确认只展示业务字段和安全策略摘要，不展示凭据、连接器内部地址或原始输入；发布 v2 后，新执行锁定 v2，历史 v1 执行仍显示 v1。
3. **按角色授权。** 只给 `report_viewer` 授权 `customer-report-search`，让 viewer 登录 Chat 能看到并执行；撤销授权后刷新，Skill 从可用列表消失，直接猜 ID 返回 403/404；`report_operator` 无授权时不能执行。
4. **停用和归档。** 管理员停用 Skill 并确认，Chat 列表不再显示且新执行被拒绝；历史执行和审计记录仍可查看。归档后尝试重新打开旧管理链接，页面显示只读终态，不能直接编辑或发布。
5. **执行长任务。** 启用 `customer-report-export`，Chat 用户填写参数并点击执行，运行卡片依次显示 queued/running/progress；点击“取消”后显示 canceled，fake Connector 收到 cancel token，不能再转为 succeeded。
6. **验证超时。** 把测试策略设置为 2 秒，执行 8 秒 Operation，页面显示 timed out；审计中有 timeout 事件，错误只显示安全错误码和建议，不显示线程堆栈、连接字符串或内部路径。
7. **验证审计。** 管理员进入“Skills → 审计”，按操作人、Skill 和时间范围筛选，看到发布、授权、执行、取消、超时事件；把审计写入模拟为失败，新的执行不进入队列，接口返回 request ID 和安全错误。
8. **验证产物下载。** 让 fake Operation 生成 `customer-report.csv`，成功卡片显示文件名、大小和下载按钮；换成未授权用户、修改 artifact ID、使用过期令牌分别下载，均被拒绝；合法下载后文件内容正确且不包含凭据。
9. **验证并发和幂等。** 连续点击两次执行或重复发送同一个 `Idempotency-Key`，页面只显示一个 execution；达到并发上限后新任务收到安全的限流提示，不影响普通 Chat。
10. **验证普通 Chat 边界。** 在普通 Chat 输入“取消刚才的 Skill”只能通过运行卡片按钮执行取消；模型文本不能直接创建新 Skill、改变授权或调用未展示的 Operation。

### M2 退出条件和演示包

- [ ] M1 演示脚本在 `SKILLS_EXECUTION_DRIVER=celery` 下继续通过。
- [ ] 版本、归档、超时、取消、审计、产物下载、RBAC 和角色授权均有服务端测试与浏览器测试，且没有仅靠前端隐藏按钮的安全断言。
- [ ] 人工验收脚本 1–10 全部通过并保存截图/录屏到 `docs/development/v1.1/acceptance/tool-skills/m2/`。
- [ ] 任何新执行都经过角色、租户、Connector 状态和审计写入检查；历史执行只读且可追溯到锁定版本。
- [ ] 产物下载不会泄露存储 key、凭据、内部 URL 或其他租户数据；超时和取消不会覆盖已写入终态。
- [ ] M2 发布标签建立后，才允许开始 M3 的包导入、Connector 管理和生产治理工作。

**M2 可演示结果：** 同一个 Tool Skill 可以安全地被迭代、授权、运行、取消、审计和下载产物；管理员和 Chat 用户在同一条闭环上看到与其角色相符的能力和状态。

---

## Milestone 3：完整 Tool Skill 能力和生产治理

**目标：** 在 M2 的安全运营闭环上补齐 Agent Skills 包导入/导出、Connector 管理、多种受控 Operation、健康检查、重试/限流/并发治理、结果脱敏策略和完整发布运行手册。

**交付结果：** 管理员可以安全预检并导入符合 Agent Skills 规范的 `SKILL.md` 包，把包中的描述映射到平台白名单 Operation 后生成草稿；可以管理租户连接和健康状态；可以在不开放脚本执行、任意 URL、自由 SQL 或包内凭据的前提下运行更多受控业务动作。

### M3 功能范围

| 领域 | 里程碑三交付内容 | 明确边界 |
|---|---|---|
| 包管理 | ZIP 预检、恶意包拒绝、冲突策略、导入草稿、脱敏导出、导入历史 | 永不执行包内 scripts/，不安装依赖，不加载插件 |
| Connector 管理 | 高权限管理员配置租户连接、健康检查、启停和安全状态 | 凭据只存引用，不在 Skill 或导出包中保存明文 |
| Operation | `database-readonly.run-template`、`internal-http.call-registered`、`file-processing.transform`、`ticketing.search/create/update` 的服务端注册和契约测试 | 不允许客户端注册 Operation、用户传完整 URL/SQL/HTTP method/header |
| 运行治理 | 重试策略、速率限制、并发配额、队列优先级、保留期、连接器熔断 | 不做跨 Skill 自主编排，不由模型自动调用 |
| 结果与审计 | 字段级脱敏、敏感输出检测、审计高级查询、健康/失败指标、告警和运行手册 | 不把原始凭据、traceback 或内部连接信息返回 Chat |
| 管理后台 | 导入/导出、Connector、Operation 映射、连接健康、运行统计和高级审计 | 仍不开放 Chat 用户创建共享 Skill |
| 用户侧 | Preset 完整管理、重试提示、限流提示、健康状态提示、产物/结果体验收 | Prompt Skill 和自动选择留到后续独立阶段 |
| 后续增强 | 私有 Skill 草稿和管理员审核流可作为独立 feature flag 设计；只产生用户私有草稿，不改变共享 Tool Skill 的发布权限 | 不作为 M3 基础闭环的完成条件，避免扩大当前权限边界 |

### M3 技术切片和任务映射

1. **安全导入/导出：Task 6。** 先对 ZIP 条目做路径、符号链接、脚本、可执行文件、密钥模式、压缩炸弹、未知二进制和大小预检，再提取到临时目录；只解析单个 `SKILL.md`、`references/` 和 `assets/`。导入始终创建草稿，管理员必须重新选择平台 Operation、分类和角色授权；导出只包含规范化的 Skill 描述和安全资源。
2. **Connector 管理：Task 4 的剩余 slice、Task 12。** 增加租户连接配置、加密凭据引用、健康检查和启停 UI；健康检查失败时新执行 fail closed，普通 Chat 不受影响。所有连接器变更写入审计，管理员 UI 只显示安全连接状态。
3. **多 Operation 契约：Task 4。** 每个 Operation 以 `OperationProtocol` 注册输入/输出 JSON Schema、side-effect 等级、超时上限、取消能力、产物能力和脱敏器；为 readonly database、registered internal HTTP、file processing 和 ticketing Operation 分别编写 fake adapter 和安全测试。
4. **运行治理：Task 8、Task 9。** 实现按租户/用户/Skill 的并发和速率限制、指数退避重试、不可重试错误分类、连接器熔断、队列优先级和执行/产物保留清理任务；重试必须新建 execution 并保留 `retry_of_execution_id`，不能覆盖原执行。
5. **管理后台补齐：Task 12。** 完成导入预检报告、冲突选择、Operation 映射、连接器管理、健康检查、导出、审计高级筛选和运行统计；所有危险操作仍使用确认弹窗，浏览器不能直接上传可执行包或调用任意接口。
6. **Chat 体验补齐：Task 13。** 完成 Preset 收藏/默认参数的完整入口、可重试错误提示、限流/熔断提示、产物过期提示、结果字段脱敏展示和窄屏/键盘无障碍体验。
7. **发布治理：Task 14。** 生成运行手册、监控指标、告警阈值、备份/恢复和数据保留策略，执行安全攻击测试、全量 E2E、迁移升级/回滚和性能基线；Prompt Skill 不纳入 M3 发布标签。

### M3 自动化验证

```powershell
$env:SKILLS_M1_CORE_ENABLED = "true"
$env:SKILLS_M2_OPERATIONS_ENABLED = "true"
$env:SKILLS_M3_IMPORTS_ENABLED = "true"
$env:SKILLS_EXECUTION_DRIVER = "celery"
$env:SKILLS_FIXED_DEMO_ROLE_MODE = "false"

pytest server/tests/test_skill_contracts.py `
  server/tests/test_skill_models.py `
  server/tests/test_skill_permissions.py `
  server/tests/test_skill_connectors.py `
  server/tests/test_skill_operations.py `
  server/tests/test_skills_api.py `
  server/tests/test_skill_import.py `
  server/tests/test_skill_preset.py `
  server/tests/test_skill_execution.py `
  server/tests/test_skill_sse.py `
  server/tests/test_skill_chat_api.py `
  server/tests/security/test_skill_security.py `
  server/tests/e2e/test_m1_tool_skill_closed_loop.py `
  server/tests/e2e/test_m2_tool_skill_operational_loop.py `
  server/tests/e2e/test_m3_tool_skill_complete.py `
  server/tests/test_skill_release_acceptance.py -q

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

**M3 自动化通过标准：** 包安全测试在“拒绝前不提取、不执行、不写入业务数据”条件下通过；所有 Operation 只通过服务端 registry 调用；全量浏览器场景、类型检查、构建、迁移和性能基线通过；任意安全测试失败都阻止发布标签。

### M3 人工验收脚本

1. **导入合法 Agent Skills 包。** 管理员打开“导入”，上传 `customer-report-export` fixture ZIP，先看到预检报告和 manifest 摘要；选择当前租户的分类和 `file-processing.transform` Operation 后应用，列表出现“未发布草稿”，不会直接发布。
2. **拒绝恶意包。** 依次上传包含 `scripts/run.py`、路径穿越、符号链接、`.env`、私钥文本、超大压缩比和未知二进制的测试包；每次都在解压前得到阻断报告，服务器没有脚本进程、临时业务 Skill 或敏感日志。
3. **冲突处理。** 再导入同一 key，选择“新建 Skill”“新建草稿版本”“取消”分别验证结果；不选择策略时不能覆盖已有 Skill。
4. **连接器健康。** 管理员配置 fake 租户连接，执行健康检查，状态从 healthy 切换为 unavailable；健康失败期间新执行被安全拒绝，恢复后可重新执行，普通 Chat 文本正常工作。
5. **受控内部 HTTP。** 选择 registered internal HTTP Operation，Skill 表单只能选择服务端注册的 service key 和 operation name；尝试输入 loopback、metadata 地址、任意 method/header 被服务端拒绝，无法形成 SSRF。
6. **只读数据库 Operation。** 选择预注册 query template，表单只出现模板允许的参数；提交 SQL、注释、union、模板名枚举字段均被拒绝，数据库 adapter 没有执行调用。
7. **结果与重试。** 触发可重试的 fake connector 错误，Chat 显示安全重试按钮；重试产生新的 execution 并链接原 execution，超过租户/Skill 配额后显示限流提示。
8. **高级审计和运行指标。** 在审计页筛选导入、连接器健康、重试、限流、结果脱敏事件；在运行统计中看到成功率、超时率、队列等待时间和产物过期清理，不显示秘密或内部路径。
9. **Preset 与响应式体验。** 用户收藏多个 Skill、设置默认参数和排序，在桌面/窄屏/键盘操作下均可稳定使用；默认参数失效时页面提示重新确认，而不是静默提交旧字段。
10. **发布和恢复。** 按运行手册执行迁移升级、备份恢复、功能开关关闭和重新开启；关闭导入开关时 API 与 UI 都拒绝导入，恢复后不丢失 M1/M2 已发布 Skill。

### M3 退出条件和演示包

- [ ] 合法包导入、恶意包拒绝、冲突处理、脱敏导出、Connector 健康和多 Operation 均有自动化与人工验收记录。
- [ ] 全量安全测试确认没有脚本执行、任意 URL、自由 SQL、包内凭据、跨租户访问、未授权下载或模型自动调用路径。
- [ ] 运行手册、监控/告警、数据保留、备份恢复和故障处理文档已提交到 `docs/development/v1.1/skills/`。
- [ ] M1/M2 的数据库、API、浏览器用例在 M3 配置下继续通过，且关闭 M3 开关不会影响已发布 Skill 的读取和执行。
- [ ] M3 标签建立后，Prompt Skill 另行立项，不把 Prompt Skill 混入本 Tool Skill 交付。

**M3 可演示结果：** 管理员可以从安全的 Agent Skills 包得到一个可审查草稿，将其映射到平台受控 Operation 后发布；系统能够在连接器异常、恶意包、权限变化和资源压力下保持可解释、可审计、fail closed。

---

## Milestone Acceptance Matrix

| 验收项 | M1 最小闭环 | M2 安全运营闭环 | M3 完整生产能力 |
|---|---|---|---|
| 管理员登录与权限 | 管理员可管理；员工管理 API 403 | 角色/权限矩阵可配置并审计 | 高权限 Connector/导入/审计分层 |
| 分类 | 新增、编辑、停用、Chat 浏览 | 停用阻断新执行并保留历史 | 排序、统计和运营筛选 |
| Tool Skill | TOOL 创建、编辑、校验、首次发布 | 版本、差异、回滚新版本、归档 | 导入草稿、脱敏导出、完整治理 |
| Operation | 一个服务端 fake Operation | 版本锁定、超时、取消、状态机 | 多 Operation、健康检查、熔断 |
| Chat | 分类浏览、手动选择、结构化表单、点击执行 | 进度、取消、终态、产物下载 | 重试、限流提示、完整 Preset 体验 |
| 安全 | 请求字段白名单、租户隔离、固定角色检查 | RBAC、审计 fail closed、二次下载鉴权 | 包扫描、SSRF/SQL/资源耗尽全量测试 |
| 自动化 | `test_m1...` + Playwright m1 | `test_m2...` + Playwright m1/m2 | `test_m3...` + 全量安全/E2E |
| 人工操作 | 10 步 M1 脚本 | 10 步 M2 脚本 | 10 步 M3 脚本 |
| 退出门槛 | 可重复演示且无未授权调用 | 可运营、可取消、可审计、可下载 | 可导入、可扩展、可上线治理 |

## Milestone-to-Task Mapping

| 现有任务 | M1：最小闭环 | M2：安全运营闭环 | M3：完整能力/生产治理 |
|---|---|---|---|
| Task 1 合同与 fixture | 受限 Tool Schema、运行请求、M1 fixture | 增加版本/取消/产物字段校验 | 增加导入元数据和多 Operation 契约校验 |
| Task 2 持久化 | 创建全部核心表和 `0009_tool_skills.py`，启用 M1 使用的字段 | 增加状态/取消/审计/产物索引和约束，补数据回填 | 增加导入历史、连接器健康、保留清理字段 |
| Task 3 权限种子 | 管理/分类/读取/执行权限，固定 EMPLOYEE 演示授权 | 可配置角色权限、角色 grant CRUD、授权变更审计 | 高权限 Connector/导入/审计分层和运营角色 |
| Task 4 Connector | 只注册 `knowledge-base.search` fake Operation | 接入 Operation 超时/取消/产物能力 | 连接器 CRUD、健康检查、readonly DB/registered HTTP/file/ticketing |
| Task 5 管理域 | 分类 CRUD、Skill CRUD、草稿、校验、首次发布 | 版本历史、差异、角色授权、停用/归档/回滚 | 导入映射、健康状态、运行统计和高级生命周期 |
| Task 6 包导入导出 | 不执行；只保留 schema/feature flag | 不开放页面和路由 | ZIP 预检、冲突处理、导入草稿、脱敏导出 |
| Task 7 SkillPreset | 收藏、显示名称、排序、默认参数 | 校验当前版本并处理版本变更/失效 | 完整 Preset 体验、排序和响应式入口 |
| Task 8 执行引擎 | Inline driver、短任务、最小事件、结果脱敏 | Celery、状态机、超时、取消、审计、产物、幂等 | 重试、配额、限流、熔断、清理和性能治理 |
| Task 9 Chat 后端/SSE | 可用列表、手动执行、快速 SSE/查询结果 | 长任务 SSE、进度、取消、终态和产物事件 | 重试/限流/健康提示和运行指标 |
| Task 10 管理列表/分类 UI | Skills 列表、分类管理、M1 过滤 | 版本/授权/审计入口和生命周期动作 | 导入/连接器/统计/高级筛选 |
| Task 11 Tool Skill 编辑器 | 基本信息、Operation、Schema、校验、发布 | 版本差异、角色授权、回滚/停用/归档确认 | 导入映射、安全报告和连接健康提示 |
| Task 12 管理扩展 UI | 不开放导入/Connector/审计页面 | 审计列表、产物/生命周期相关管理 | 导入导出、Connector、健康、审计高级查询 |
| Task 13 Chat UI | 分类浏览、手动选择、表单、执行、Preset | 进度、取消、超时、错误、产物下载 | 重试、限流、脱敏展示、完整响应式体验 |
| Task 14 集成发布 | M1 acceptance matrix 和 m1 浏览器脚本 | M2 RBAC/长任务/审计/产物验收 | 全量安全、性能、运行手册、M3 发布 |

## 里程碑实施顺序和分支策略

1. **M1 实施顺序：** Task 1 → Task 2 → Task 3 → Task 4（fake slice）→ Task 5（management slice）→ Task 7 → Task 8（inline slice）→ Task 9（Chat backend slice）→ Task 10/11 → Task 13（Chat UI slice）→ Task 14（M1 gate）。每完成一个任务执行该任务已有的 focused test 和独立 commit，不跨越 M1 范围实现导入或完整 RBAC UI。
2. **M2 实施顺序：** 以 M1 发布标签为基线，先完成 Task 3/5 的 RBAC 与版本，再完成 Task 8 的 Celery/状态机，随后 Task 9 的 SSE、Task 11/12 的后台治理页面、Task 13 的运行卡，最后 Task 14 M2 gate。任何 M2 任务都必须先验证 M1 的 e2e 仍然通过。
3. **M3 实施顺序：** 以 M2 发布标签为基线，先完成 Task 6 的 ZIP 安全导入导出，再完成 Task 4/12 的 Connector 管理和多 Operation，接着完成 Task 8/9 的运行治理，最后 Task 13/14 的体验、监控、运行手册和全量安全验收。
4. **分支与回滚：** 每个里程碑从上一个发布标签创建 `codex/tool-skills-m1`、`codex/tool-skills-m2`、`codex/tool-skills-m3` 分支；上线前在 staging 执行同一套迁移和验收命令。若 M2/M3 开关关闭，M1 已发布 Skill 的读/执行接口必须保持可用；若迁移回滚失败，停止发布，不执行手工删表或跨版本强制修改。
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
| `server/tests/e2e/test_m1_tool_skill_closed_loop.py` | M1 服务端端到端闭环：管理员创建/发布、员工浏览/执行、Preset 和安全负向请求。 |
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

  Cover the tenant boundary, uniqueness, lifecycle fields, and version immutability:

  ```python
  def test_skill_key_is_unique_per_tenant(db, tenant_a, tenant_b):
      create_skill(db, tenant_a, key="customer-report-export")
      create_skill(db, tenant_b, key="customer-report-export")
      with pytest.raises(IntegrityError):
          create_skill(db, tenant_a, key="customer-report-export")

  def test_preset_and_grant_are_tenant_scoped(db):
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
  - `SkillVersion`: `skill_id`, `version_number`, `package_manifest`, `input_schema`, `presentation_config`, `execution_policy`, `connector_operation_id`, `status`, `created_by_user_id`, `published_at`, `published_by_user_id`, `content_hash`; unique `(skill_id, version_number)`.
  - `SkillRoleGrant`: `skill_version_id`, `role_id`, `can_execute`; unique `(skill_version_id, role_id)`.
  - `SkillPreset`: `tenant_id`, `user_id`, `skill_id`, `display_name`, `is_favorite`, `default_input`, `display_order`; unique `(user_id, skill_id)` and no role/connector fields.
  - `Connector`: platform key, name, type, status, connector version, health status, timestamps.
  - `ConnectorOperation`: connector ID, key, display name, input/output contracts, side-effect level, timeout ceiling, allowed tenant config, status; unique `(connector_id, key)`.
  - `ConnectorConnection`: tenant ID, connector ID, safe display name, encrypted secret reference, non-secret config, status, last health check; unique `(tenant_id, connector_id)`.
  - `SkillExecution`: tenant/skill/version/session/message references, requester, role snapshot, status, timestamps, duration, request ID, operation snapshot, redacted input/result, safe error fields, retry/cancel references.
  - `SkillExecutionEvent`: execution ID, sequence, event name, safe payload, created timestamp; unique `(execution_id, sequence)`.
  - `SkillArtifact`: execution ID, storage key, safe filename, MIME, size, checksum, expiry, classification, download policy.
  - `SkillPackageImport`: tenant/uploader, safe filename, package hash, manifest summary, status, validation report, conflict resolution, created skill/version references.

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

### Task 3: Add Skill permissions and idempotent seed upgrades

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

  Expected: PASS, with no duplicate rows and no regression in existing permission checks.

- [ ] **Step 5: Commit the permission slice.**

  ```powershell
  git add server/app/services/seed_service.py server/tests/test_skill_permissions.py
  git commit -m "feat: seed tool skill permissions"
  ```

### Task 4: Register controlled Connector Operations and tenant connections

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

  - `knowledge-base.search`: accept query, optional category/space identifiers, and bounded page size; derive accessible knowledge scope from `AccessContext`, never from an untrusted tenant/user field.
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

### Task 5: Implement categories, Skill CRUD, versions, role grants, and lifecycle APIs

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

  Use seeded admin, employee, second-tenant, active/inactive category, role, and connector fixtures. Cover these cases:

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

  Every repository query includes `tenant_id == context.tenant_id`. Category deletion returns a conflict when any Skill exists; disabling does not mutate Skill status.

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

  A Skill create/edit request accepts `skillType` only when it is `TOOL`; return `SKILL_TYPE_NOT_AVAILABLE` for `PROMPT` in this phase. Publishing requires: active category, active Skill, exactly one active Connector Operation, valid input schema, policy within operation ceilings, at least one role grant, no unresolved import mapping, and a successful audit insert in the same transaction. Publishing moves the old version to `SUPERSEDED`; it never updates a published row in place.

- [ ] **Step 5: Add available-definition and role-grant behavior.**

  Add `GET /skills/available`, `GET /skills/{skill_id}/available-definition`, and admin role-grant mutations under `/skills/{skill_id}/versions/{version_id}/role-grants`. The available query must join the current published version, active category, active connector/operation, the current user's roles, and `SKILL_READ`/`SKILL_EXECUTE`. It must return no row for an unauthorized user, even if the user guesses the key or ID. The definition response omits `connector_key`, `operation_key`, internal endpoint, credentials, role IDs, and raw package files.

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

### Task 7: Add private user SkillPreset support

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

  Use the already-migrated `skill_presets` table and expose only these fields:

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

### Task 8: Implement the Skill execution engine, Celery worker, audit events, and artifacts

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

  Cover every legal and illegal transition, authorization formula, idempotency, audit failure, timeout, cancellation, retry, and output limit:

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

  `SkillExecutionService.create` receives `AccessContext`, `chat_session_id`, `skill_id`, `input`, and an `idempotency_key` from a request header. It performs this ordered transaction before enqueueing:

  1. Resolve the current tenant's Skill by ID; never accept version, connector, operation, role, URL, SQL, or credentials from the request body.
  2. Check `SKILL_EXECUTE`, `CHAT_WRITE`, session ownership, active category, Skill `PUBLISHED`, current published version, role grant, active Connector, active Operation, and tenant connection.
  3. Validate input against the locked version's normalized schema and operation contract; reject unknown fields and size/format violations.
  4. Build a role snapshot from `AccessContext`, redact the input with the schema's sensitive paths, and create `SkillExecution(status="PENDING")` with version/operation snapshots and a generated request ID.
  5. Write the initial `skill_run_started` audit/event row in the same transaction. If this insert fails, roll back and do not enqueue.
  6. Commit, then enqueue the Celery task with execution ID. If queue submission fails, persist a safe `QUEUE_FAILED` terminal error and emit no success event.

  Use the design state machine exactly:

  ```text
  PENDING -> VALIDATING -> QUEUED -> RUNNING -> SUCCEEDED
                              |         |------> FAILED
                              |         |------> TIMED_OUT
                              |         |------> CANCELED
                              +-------> REJECTED
  ```

  Store every transition as a sequenced event with only safe status labels and progress messages.

- [ ] **Step 4: Implement the Celery task and operation execution context.**

  `skill_tasks.py` must open its own `SessionLocal` session, re-read the execution and locked version, transition to `VALIDATING`, call the registry operation's availability check, then transition to `RUNNING`. It must pass a `SkillExecutionContext` containing cancellation signal, redacted logger, tenant/user/role snapshot, and artifact writer. It must never trust a mutable current Skill pointer after the execution was created.

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

### Task 9: Integrate Tool Skill runs with Chat sessions and SSE

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

  Add tests for ownership, request shape, message persistence, SSE event order, and ordinary Chat isolation:

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

  The route validates the session before opening the stream, calls `SkillExecutionService.create`, persists a `SKILL_REQUEST` message with a safe rendered summary, then streams status events. It must not pass client `skillVersionId`, `connectorKey`, `operationKey`, role, URL, SQL, or credentials through to the service. The result message is created/updated from safe result data only. If a request fails before streaming, return the project's structured 4xx error with request ID.

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

  it('hides admin Skill routes without SKILL_MANAGE', () => {
    expect(visibleRoutesFor({ permissions: ['CHAT_READ'] })).not.toContain('#skills');
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

  Add routes:

  ```text
  #skills              -> SkillPage          (SKILL_MANAGE)
  #skills/categories   -> SkillCategoriesPage(SKILL_CATEGORY_MANAGE)
  #skills/new          -> SkillEditorPage    (SKILL_MANAGE, hidden)
  #skills/:id          -> SkillEditorPage    (SKILL_MANAGE, hidden)
  #skills/import       -> SkillImportPage    (SKILL_MANAGE, hidden)
  #skills/connectors   -> SkillConnectorsPage(SKILL_CONNECTOR_MANAGE, hidden)
  #skills/audit        -> SkillAuditPage     (SKILL_AUDIT_READ, hidden)
  ```

  Extend `SidebarIconName` with `skills` and show one “Skills” navigation item only when the current user has `SKILL_MANAGE`, `SKILL_CATEGORY_MANAGE`, `SKILL_CONNECTOR_MANAGE`, or `SKILL_AUDIT_READ`. The route renderer must still check the individual permission, so typing a hash cannot bypass the gate.

- [ ] **Step 4: Implement the Skills list page.**

  `SkillPage` must provide:

  - title, count, “新建 Tool Skill”, “导入 Skill 包”, “分类管理”, “连接器”, and “审计” actions;
  - search by key/name/description with server-side debounce;
  - filters for category, status (`DRAFT`, `PUBLISHED`, `DISABLED`, `ARCHIVED`), operation, and authorized role;
  - table columns: icon/name/key, category, type, current version, status, authorized roles, 7/30-day execution count, failure rate, updated time, and action menu;
  - row actions: open editor, create draft version, validate, test, publish, disable/enable, rollback, export, archive;
  - disabled action buttons with tooltips explaining the server validation that is still missing;
  - empty state explaining that Chat users can only use published, role-authorized Tool Skills;
  - loading skeleton, API error with request ID, pagination, and responsive card layout below 900px.

  The list component must not infer availability from a status badge; every mutation handles the authoritative API response and refreshes the detail/list queries.

- [ ] **Step 5: Implement category management.**

  `SkillCategoriesPage` and `SkillCategoryPanel` must support create/edit, icon selection from a fixed safe set, display order, active/disabled state, counts, and drag-free up/down ordering buttons. Disabling requires `ConfirmActionDialog` text that explains existing history remains but new Chat executions stop. Delete is shown only when the server reports zero references; otherwise show “停用” and the conflict reason.

- [ ] **Step 6: Run front-end checks and commit the navigation/list slice.**

  ```powershell
  cd web/admin
  npm test -- --run src/features/skills/utils/skillFormValidation.test.ts
  npm run typecheck
  npm run lint
  npm run build
  ```

  Expected: PASS; routes, query types, list, filters, category actions, and permission gates compile and the production build succeeds.

  ```powershell
  git add web/admin/package.json web/admin/package-lock.json web/admin/src/routes/index.tsx web/admin/src/api/queryClient.ts web/admin/src/features/skills web/admin/src/styles/index.css web/admin/src/styles/skills.css
  git commit -m "feat: add skills admin catalog"
  ```

### Task 11: Build the administrator Tool Skill editor and publish workflow

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

- [ ] **Step 1: Write failing editor validation tests.**

  Add pure-function tests for each editor section before rendering components:

  ```ts
  it('builds a Tool Skill draft payload without runtime-control fields', () => {
    const payload = toSkillDraftPayload({
      basic: { key: 'customer-report-export', name: '客户报表导出', categoryId: 'cat-1' },
      operationId: 'op-1',
      fields: [{ name: 'date_from', type: 'date', required: true }],
      roles: ['role-employee'],
    });
    expect(payload).toMatchObject({ skillType: 'TOOL', connectorOperationId: 'op-1' });
    expect(JSON.stringify(payload)).not.toContain('connectorKey');
    expect(JSON.stringify(payload)).not.toContain('password');
  });

  it('blocks publish when the draft has no operation, no role, or unsafe policy', () => {
    const issues = getPublishBlockers(incompleteDraft);
    expect(issues.map((item) => item.code)).toEqual(
      expect.arrayContaining(['OPERATION_REQUIRED', 'ROLE_REQUIRED', 'POLICY_EXCEEDS_CEILING']),
    );
  });

  it('requires confirmation for external writes and file writes', () => {
    expect(policyForOperation({ sideEffectLevel: 'EXTERNAL_WRITE' }).requiresConfirmation).toBe(true);
    expect(policyForOperation({ sideEffectLevel: 'FILE_WRITE' }).requiresConfirmation).toBe(true);
  });

  it('does not allow an admin to change a published version in place', () => {
    expect(editorMode({ versionStatus: 'PUBLISHED' })).toBe('CREATE_DRAFT_VERSION');
  });
  ```

- [ ] **Step 2: Run the tests and confirm the editor modules are absent.**

  ```powershell
  cd web/admin
  npm test -- --run src/features/skills/utils/skillFormValidation.test.ts
  ```

  Expected: FAIL with missing editor helper functions/components.

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

- [ ] **Step 3: Implement Chat Skill API and typed state.**

  `web/admin/src/features/chat/api/skillApi.ts` exposes:

  ```ts
  getAvailableCategories(): Promise<SkillCategorySummary[]>;
  getAvailableSkills(categoryId?: string): Promise<SkillSummary[]>;
  getAvailableDefinition(skillId: string): Promise<SkillAvailableDefinition>;
  getPreset(skillId: string): Promise<SkillPreset | null>;
  savePreset(skillId: string, payload: SkillPresetWrite): Promise<SkillPreset>;
  streamSkillRun(sessionId: string, body: { skillId: string; input: Record<string, unknown> }, handlers, options): Promise<void>;
  ```

  The request builder must create exactly `{ skillId, input }`. It may send an `Idempotency-Key` header generated for the run, but it must never put version IDs, connector/operation keys, role IDs, URL, SQL, or credentials into the body. Types must mark runtime-control fields as impossible in the Chat form state.

- [ ] **Step 4: Implement the Skills drawer and details flow.**

  Add a “Skills” button beside the existing Chat composer. `SkillDrawer` contains:

  - active category tabs/list from the server;
  - search and “收藏” filter;
  - available Skill cards with icon, name, description, category, favorite state, side-effect badge, and version;
  - loading/error/empty states that include the request ID when available;
  - no card for a Skill the server did not return.

  Clicking a card opens `SkillDetailPanel` with purpose, suitable scenarios, input/output description, limits, side-effect level, confirmation text, and current preset defaults. Keep the ordinary natural-language composer visible but separate; selecting a Skill must not put its fields into the free-text message box.

- [ ] **Step 5: Implement the schema-driven input form and private preset controls.**

  `SkillInputForm` renders only the server's restricted schema types and checks required/min/max/enum/date/file-reference constraints before enabling execution. It displays field help and safe default values. Unknown schema keywords render a blocking “无法渲染” state rather than falling back to a free-form JSON editor.

  Provide “收藏”, custom display name, “保存为默认参数”, “恢复默认”, and display order actions through `SkillPreset`. Saving a preset sends only the four allowed fields and validates against the current available definition. If the Skill is disabled or the published version changes, re-fetch the definition and revalidate defaults before allowing execution. No control enables creation, sharing, publishing, operation changes, or role changes.

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

- [ ] **Step 1: Write the release acceptance matrix as executable tests.**

  `test_skill_release_acceptance.py` must cover at least:

  | Area | Acceptance assertion |
  |---|---|
  | Admin create | Admin creates a category and Tool Skill draft. |
  | Schema | Invalid root/additional property/runtime field is rejected. |
  | Connector | Only seeded registry operations are selectable. |
  | Publish | Operation, active category, role, policy, and audit are required. |
  | RBAC | Employee sees/executes only granted published Skills; no manage API. |
  | Versioning | Published edit creates a new draft; old execution remains pinned. |
  | Import | Valid package becomes draft; malicious package is rejected before extraction. |
  | Conflict | Same key requires explicit new/append/cancel choice. |
  | Execution | Input, role, tenant, connector, and audit checks happen before invocation. |
  | Chat | Manual click is required; ordinary text cannot invoke Skills. |
  | SSE | All seven event types and terminal status are delivered/replayable. |
  | Output | Sensitive data, tracebacks, storage keys, and credentials are absent. |
  | Resource | Timeout, concurrency, rate, output, artifact, and cancellation limits hold. |
  | Lifecycle | Category/Skill/Connector disable prevents new runs but preserves history. |

- [ ] **Step 2: Add malicious-input and resource-exhaustion security tests.**

  `server/tests/security/test_skill_security.py` must include:

  - ZIP path traversal, absolute path, duplicate entry, symlink, encrypted archive, compression bomb, member-count, compressed/uncompressed/member-size, and unknown binary tests;
  - scripts and executable file tests for `.py`, `.js`, `.sh`, `.ps1`, `.bat`, native executables, `node_modules`, `.venv`, `__pycache__`, and `.env`;
  - private key, bearer token, cloud key, database URL, and secret-assignment pattern tests in markdown/references/assets;
  - internal HTTP SSRF attempts using loopback, link-local, metadata, alternate IP notation, redirects, and user-supplied host/path/method headers;
  - database free SQL, comment/union injection, template-key enumeration, cross-tenant parameter tests;
  - forged `skillVersionId`, `connectorKey`, `operationKey`, `roleIds`, URL, SQL, and credential fields on API requests;
  - sensitive output path, error traceback, result-size, artifact path, and signed-download replay tests;
  - concurrency/rate/timeout/queue tests proving an operation cannot exhaust worker resources.

  Every security test must assert a safe public error and confirm no connector call, no package execution, and no privileged data in normal logs/audit exports.

- [ ] **Step 3: Add end-to-end admin-to-Chat coverage.**

  `server/tests/e2e/test_tool_skill_e2e.py` must run this sequence against a temporary tenant:

  1. Seed permissions, roles, categories, registry operations, and a safe connection.
  2. Admin creates `customer-report-export`, configures schema/presentation/policy, grants `EMPLOYEE`, validates, test-runs, and publishes version 1.
  3. Employee lists available Skills by category and receives only that published definition.
  4. Employee starts a run through an owned Chat session with `{skillId, input}`, receives ordered SSE events, and reads a safe result/artifact.
  5. Admin edits and publishes version 2; a version-1 run still reports version 1 and its original operation snapshot.
  6. Admin disables the Skill; a new employee run is rejected while history remains queryable.
  7. Admin imports a valid package into a draft, resolves its operation/role mapping, and confirms it cannot auto-publish.

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
- [ ] 设计中的七类 Skill SSE 事件（started、status、progress、result、artifact、error、done）都有 schema、服务端发送/重放测试和前端展示路径。
- [ ] 所有用户侧/管理侧 API、后台页面和 Chat 页面都映射到对应 Task；M1/M2/M3 的浏览器验收不会依赖手工修改数据库。
- [ ] 设计安全威胁中的包扫描、SSRF、自由 SQL、凭据泄露、跨租户访问、资源耗尽和下载越权均有命名控制与自动化测试。
- [ ] 所有权限和授权公式都由服务端执行；前端过滤只用于体验，不能作为安全控制。
- [ ] Skill 和 SkillExecution 状态机均有合法/非法转换测试；终态不可被晚到的 worker 结果覆盖。
- [ ] `POST /chat/sessions/{session_id}/skill-runs` 的客户端请求体始终只包含 `skillId` 和结构化 `input`；服务端拒绝 version/connector/operation/role/URL/SQL/credential 注入。
- [ ] 任何执行都锁定租户、已发布版本、Operation 契约和角色快照；跨租户、未授权、停用、归档、连接器不可用和审计写入失败均 fail closed。
- [ ] M1 不允许 Chat 用户创建、导入、发布或共享真正的 Skill；用户个性化只写入私有 `SkillPreset`。
- [ ] M2 的版本、归档、超时、取消、审计、产物下载和 RBAC 都有自动化测试和人工操作证据。
- [ ] M3 的包导入在解压前完成安全预检，永不执行包内脚本；Connector 和 Operation 只能由服务端白名单注册。
- [ ] `git diff --check`、后端 focused suite、前端 typecheck/lint/build、对应 marker 的 Playwright 和迁移 upgrade/downgrade 均通过。
- [ ] 完成 M3 后另行立项 Prompt Skill；本计划不把 Prompt Skill、模型自动选择、自治编排或共享用户 Skill 混入 Tool Skill 发布。

## 执行方式选择

计划已按三个可独立验收的里程碑拆分。实现阶段推荐使用 `subagent-driven-development`：每个 Task 由独立 worker 完成，主线程在任务之间审查 diff 和测试结果；如果希望在同一会话中连续实施，也可以使用 `executing-plans`，按 M1/M2/M3 的 gate 分批执行，不能跳过里程碑验收。
