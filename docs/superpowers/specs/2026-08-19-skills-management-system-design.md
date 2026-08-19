# Skills 管理系统设计

- **状态：** 已确认，待编写实施计划
- **日期：** 2026-08-19
- **范围：** 第一阶段工具型 Skills；第二阶段提示词型 Skills 的兼容性预留
- **决策人：** 产品负责人

## 1. 背景与目标

灵犀当前具备企业知识库 Chat、会话与消息持久化、SSE 流式响应、RBAC、模型配置、调用日志和异步任务基础设施。现有 Chat 只能完成知识库问答；它不能让用户在明确选择一个受控能力后执行检索、业务查询、报表导出、内部 API 操作、工单操作或文件处理任务。

本项目建立 Skills 管理系统，使管理员能够把受控平台能力封装为可授权、可审计、可导入导出的 Skill，并使 Chat 用户可以按分类手动选择并运行其有权限使用的 Skill。

### 1.1 第一阶段目标

1. 建立 Tool Skill 的分类、生命周期、版本、角色授权和审计模型。
2. 支持管理员创建、编辑、启停、导入、导出和回滚 Tool Skill。
3. 支持 Chat 用户按分类浏览本人有权使用的 Skill，填写结构化参数，并手动触发执行。
4. 将执行进度、结果、失败和可下载产物以 SSE 事件和 Chat 消息卡方式呈现。
5. 只允许服务端已经注册、审核和配置的连接器执行实际操作；不能把导入的 Skill 包视为可执行插件。
6. 使用 Agent Skills 规范作为 Skill 包的交换格式，同时把灵犀专有的授权、连接器绑定、发布状态和凭据管理留在平台内。

### 1.2 第二阶段目标

第二阶段在不迁移一阶段数据的前提下增加 Prompt Skill：管理员可以封装专业提示词、变量、知识库范围、模型策略和结构化输出约束。Prompt Skill 复用一阶段的分类、角色授权、版本、导入导出和审计体系。

### 1.3 非目标

以下能力不属于第一阶段：

- LLM 自动选择或自动执行 Skill；
- 多个 Skill 的自动串联、规划或自治 Agent；
- 执行导入包中的脚本或上传的 Python/JavaScript 插件；
- 管理员填写任意 URL、任意请求头或用户提供的完整外部 URL；
- 由用户编写自由 SQL；
- Prompt Skill 的创建和执行入口。

## 2. 已确认的产品决策

| 决策 | 结论 |
| --- | --- |
| 建设节奏 | 分两期。第一期实现 Tool Skill，第二期实现 Prompt Skill。 |
| 调用方式 | Chat 用户手动选择 Skill、填写参数并显式点击执行。 |
| 角色控制 | 按既有 RBAC 角色授权。前端负责过滤展示，后端每次执行强制校验。 |
| 分类 | Skill 可归属一个管理员维护的分类；Chat 按分类展示。 |
| 管理能力 | 管理员可创建、编辑、启停、导入、导出、查看版本和审计。 |
| 包标准 | 使用 Agent Skills 标准包；`SKILL.md` 为入口，`references/`、`assets/` 可选。 |
| 安全边界 | 不执行 `scripts/`；不接受包内凭据；仅可绑定平台预注册、审核的连接器和操作。 |
| 执行方式 | 一项 Tool Skill 在一阶段绑定一个受控 Connector Operation。 |

## 3. 术语与领域模型

### 3.1 术语

| 术语 | 定义 |
| --- | --- |
| 分类（Category） | 用于管理与 Chat 浏览的 Skill 分组，例如“知识查询”“数据分析”“业务协作”“文件处理”。 |
| Skill | 面向用户的业务能力定义。Skill 自身不携带可执行代码。 |
| Skill 版本 | 一个不可变的 Skill 配置快照；已发布版本不能原地修改。 |
| Tool Skill | 绑定一个受控连接器操作，并通过服务端执行器完成任务的 Skill。 |
| Prompt Skill | 第二阶段引入的提示词、变量、知识库和模型策略封装。 |
| 连接器（Connector） | 平台开发和运维团队注册、审核和运行的集成能力。 |
| 连接器操作（Operation） | 连接器暴露的一个固定、安全、具有明确输入输出契约的动作。 |
| 执行（Execution） | 用户在会话中发起的一次 Skill 运行。 |
| 产物（Artifact） | 执行产生的受控文件或大结果，存储为权限受限引用而非直接内嵌。 |

### 3.2 领域关系

```text
SkillCategory 1 ── * Skill 1 ── * SkillVersion
                         │              │
                         │              ├── 1 ConnectorOperation
                         │              ├── * RoleGrant
                         │              └── * SkillExecution
                         │
ChatSession 1 ── * ChatMessage 1 ── 0..1 SkillExecution
Connector 1 ── * ConnectorOperation
Connector 1 ── * ConnectorConnection
```

### 3.3 关键数据实体

#### `skill_categories`

- `id`、`tenant_id`、`key`、`name`、`description`
- `icon`、`display_order`、`status`（`ACTIVE` / `DISABLED`）
- 创建、更新和审计字段
- 在同一租户内 `key` 唯一。

#### `skills`

- `id`、`tenant_id`、`category_id`
- `key`（稳定机器标识）、`name`、`description`、`icon`
- `skill_type`（第一期只允许 `TOOL`；数据库同时保留 `PROMPT` 枚举值）
- `status`（见第 8 节）、`current_published_version_id`
- `created_by_user_id`、时间戳和乐观锁版本。

#### `skill_versions`

- `id`、`skill_id`、`version_number`
- `package_manifest`：经过校验并规范化的 `SKILL.md` 内容与允许资源清单
- `input_schema`：参数 JSON Schema
- `presentation_config`：表单标签、说明、结果展示规则
- `execution_policy`：超时、并发、频率限制、脱敏规则和副作用标签
- `connector_operation_id`：一阶段 Tool Skill 的唯一绑定
- `status`（`DRAFT` / `PUBLISHED` / `SUPERSEDED` / `REJECTED`）
- `published_at`、`published_by_user_id`。

#### `skill_role_grants`

- `id`、`skill_version_id`、`role_id`
- `can_execute`（第一期固定为 `true`，为以后拆分可见与执行权限预留）
- 同一版本和角色组合唯一。

#### `connectors` 与 `connector_operations`

- Connector 由平台级注册表维护：`key`、`name`、`type`、`status`、`connector_version`。
- Operation 固定定义：`key`、`display_name`、`input_contract`、`output_contract`、`side_effect_level`、`timeout_ceiling`、`allowed_tenant_config`。
- 用户或 Skill 包不能创建任意 Operation。只有具备连接器管理权限的管理员才能为已部署连接器创建连接配置和凭据引用。

#### `skill_executions`

- `id`、`tenant_id`、`skill_id`、`skill_version_id`
- `chat_session_id`、`request_message_id`、`result_message_id`
- `requested_by_user_id`、`requested_role_snapshot`
- `status`、`started_at`、`finished_at`、`duration_ms`
- `request_id`、`connector_key`、`operation_key`
- `input_redacted`、`result_summary_redacted`、`error_code`、`error_message_safe`
- `retry_of_execution_id`、`canceled_by_user_id`。

#### `skill_artifacts`

- `id`、`execution_id`、`storage_key`、`file_name_safe`、`mime_type`、`size_bytes`
- `checksum`、`expires_at`、`classification`、`download_policy`
- 文件下载只通过短时签名且经过当前用户权限校验的 URL 提供。

#### `skill_package_imports`

- `id`、`tenant_id`、`uploaded_by_user_id`
- `source_file_name_safe`、`package_hash`、`manifest_summary`
- `status`、`validation_report`、`conflict_resolution`
- `created_skill_id`、`created_version_id`、时间戳。

## 4. Agent Skills 包兼容策略

### 4.1 包结构

导入和导出的最小包必须具有：

```text
<skill-name>/
└── SKILL.md
```

允许携带：

```text
<skill-name>/
├── SKILL.md
├── references/
└── assets/
```

系统忽略或拒绝以下内容：

```text
scripts/
node_modules/
.venv/
__pycache__/
*.py
*.js
*.sh
*.ps1
.env
```

安全策略以“拒绝默认执行”为原则：即使导入包包含可执行脚本，系统绝不加载、解释或运行这些文件。对于 `scripts/` 和任何禁用类型，导入预检默认失败；管理员只能删除这些文件后重新导入，不能点击忽略后继续发布。

### 4.2 `SKILL.md` 映射

`SKILL.md` 中标准 frontmatter 的 `name`、`description` 作为包的基础标识与说明。灵犀将专有映射信息置于 `metadata.lingxi`，但把以下内容只保存于平台数据库，且不从包中直接生效：角色授权、连接器凭据、内部端点、发布状态、执行频率、运行日志和审计数据。

示例：

```yaml
---
name: customer-report-export
description: 根据筛选条件导出客户报表。
metadata:
  lingxi:
    category_key: data-analysis
    connector_key: reporting
    operation_key: export_customer_report
    input_schema_ref: customer-report-export-v1
    requires_confirmation: true
---
```

导入时，`connector_key` 和 `operation_key` 只是候选映射。系统必须展示管理员确认页，由管理员将其绑定到当前租户已启用的实际 Connector Operation；找不到匹配对象时只允许保存为未发布草稿。

### 4.3 导入和导出边界

- 导入格式：单个 ZIP 文件，解压后必须只有一个根目录和一个 `SKILL.md`。
- 导入限制：压缩包、解压后总大小、单文件大小和资产类型均使用服务端配置的白名单与上限。
- 导入扫描：路径穿越、重复/冲突文件、符号链接、压缩炸弹、脚本、密钥模式、未知二进制类型均必须被拒绝。
- 同 `key` 的 Skill 不能静默覆盖。管理员必须选择新建、创建新草稿版本或取消。
- 导出只包含 `SKILL.md`、被允许的说明文档与资产；不导出密钥、内部连接信息、角色名单、执行记录、用户输入或结果。

## 5. 功能设计

### 5.1 分类管理

具备 `SKILL_CATEGORY_MANAGE` 的管理员可以创建、编辑、排序和启停分类。

- 分类禁用后：所属 Skill 不再在 Chat 的可用清单中出现，也不能创建新执行。
- 历史 Skill 和执行记录保留，可在审计页面查看。
- 禁用分类不改变 Skill 本身的发布状态；重新启用分类后，满足其他条件的 Skill 自动恢复可见。
- 删除分类只允许在没有 Skill 时发生；否则只能禁用。

### 5.2 Skill 管理

具备 `SKILL_MANAGE` 的管理员可以：

1. 创建 Tool Skill 基本资料并选择分类；
2. 选择一个租户可用且已审核的 Connector Operation；
3. 配置输入参数 schema、表单展示、结果展示和执行策略；
4. 为版本授予一个或多个角色；
5. 保存草稿，发起测试执行，发布、停用、归档或回滚；
6. 导入或导出安全包；
7. 查看版本差异、执行统计和失败摘要。

第一期一个已发布版本必须绑定恰好一个 Operation。一个 Skill 可以有多个版本，但任何时刻最多一个当前发布版本。编辑已发布 Skill 时，系统创建新草稿版本；旧版本继续服务于历史审计和仍在运行的任务。

### 5.3 连接器管理

具备 `SKILL_CONNECTOR_MANAGE` 的管理员维护租户级连接配置；连接器类型和 Operation 契约由系统代码/部署配置提供，不由 Skill 包提供。

首批连接器类别：

| 连接器 | 第一阶段边界 |
| --- | --- |
| `knowledge-base` | 在当前用户可访问的知识库和分类范围内检索。 |
| `database-readonly` | 仅运行预审核的参数化只读查询模板或存储过程。 |
| `internal-http` | 仅运行预配置服务、HTTP 方法、路径模板和请求契约的操作。 |
| `file-processing` | 只处理允许格式、大小和操作白名单内的文件，并生成受控产物。 |
| `ticketing` | 调用预配置的创建、查询、更新工单操作；变更字段使用严格 schema。 |

连接器配置中的密钥和令牌只能作为加密 Secret 引用保存，并遵循已有系统的密钥管理与日志脱敏逻辑。Skill 管理页面绝不返回凭据明文。

### 5.4 Chat 使用体验

Chat 新增 Skills 面板，按以下顺序工作：

1. 客户端请求可用 Skills；服务端使用当前用户角色和租户过滤。
2. 用户根据分类筛选，并打开一个 Skill 的说明卡。
3. 用户查看用途、输入说明、副作用等级、运行限制和必填字段。
4. 前端根据 `input_schema` 渲染受限表单；不提供自由 JSON 或自由 URL 输入。
5. 用户点击“执行”后，系统在当前 Chat 会话中创建一条 `SKILL_REQUEST` 消息和一条待更新的 `SKILL_RESULT` 消息。
6. 浏览器订阅该运行的 SSE，展示“已校验”“等待执行”“运行中”“生成结果”“完成/失败/已取消”等事件。
7. 完成后结果卡显示安全摘要、结构化字段和受控下载产物；失败显示用户可理解的错误和在策略允许时的重试按钮。

Chat 不自动选中或自动执行任何 Skill。普通聊天消息和 Skill 消息共享会话历史，但其消息类型、Skill 名称、版本和执行状态必须可区分。

### 5.5 执行引擎

执行引擎按以下固定流程运行：

```text
POST Chat Skill 执行请求
  → 验证 CHAT_WRITE、SKILL_EXECUTE 与角色授权
  → 验证分类、Skill、版本、连接器和 Operation 状态
  → 验证输入 schema、文件和内容安全规则
  → 创建 SKILL_REQUEST 消息与 SkillExecution 审计记录
  → 发送 run_started SSE 事件
  → 在执行器中调用指定 Connector Operation
  → 推送进度、日志摘要和产物就绪事件
  → 脱敏并持久化结果摘要、结构化输出、产物引用
  → 写入 SKILL_RESULT 消息、完成 SkillExecution、发送 done 事件
```

长耗时操作必须进入受控后台任务队列，并以执行 ID 返回给 Chat；短操作可以同步开始，但仍必须受统一超时和取消接口控制。任何执行异常都必须转换为稳定错误码和安全错误描述；底层堆栈、认证头、SQL、内部 URL 和密钥不进入 Chat 或普通日志。

### 5.6 审计与可观测性

每次导入、发布、停用、授权变更、执行、取消和重试必须具有不可变审计事件。至少记录：

- 租户、用户、角色快照、Skill、Skill 版本、连接器、操作和请求 ID；
- 时间、状态转换、耗时、结果大小、产物数量和重试关系；
- 已脱敏的参数摘要、结果摘要和错误码；
- 导入文件哈希、校验结论和冲突处理方式。

提供管理员审计列表，可按 Skill、连接器、用户、角色、状态、时间和错误码筛选。指标至少包括执行总量、成功率、分位耗时、超时率、失败类型、取消数、连接器可用性和导入拒绝数。

## 6. 权限模型

沿用项目现有角色和权限体系，并新增：

| 权限 | 授权对象 | 含义 |
| --- | --- | --- |
| `SKILL_READ` | 用户角色 | 查看自己有资格使用的分类和 Skill。 |
| `SKILL_EXECUTE` | 用户角色 | 请求执行被角色授权的已发布 Skill。 |
| `SKILL_MANAGE` | 管理员角色 | 创建、编辑、导入、发布、停用、归档和导出 Skill。 |
| `SKILL_CATEGORY_MANAGE` | 管理员角色 | 维护分类。 |
| `SKILL_CONNECTOR_MANAGE` | 高权限管理员 | 维护连接器配置、凭据引用和可用 Operation。 |
| `SKILL_AUDIT_READ` | 管理员/审计员角色 | 查看执行和导入审计。 |

执行授权公式：

```text
允许执行 =
  has_permission(SKILL_EXECUTE)
  AND has_permission(CHAT_WRITE)
  AND SkillCategory.status == ACTIVE
  AND Skill.status == PUBLISHED
  AND Skill.current_published_version.status == PUBLISHED
  AND 当前角色存在对应 SkillRoleGrant
  AND Connector.status == ACTIVE
  AND ConnectorOperation.status == ACTIVE
```

服务端从认证上下文计算当前角色，不接受前端传来的角色、连接器或权限判断结果。对于数据类连接器，连接器还必须将当前用户和租户上下文传入其行级权限或业务权限校验。

## 7. 安全设计

| 威胁 | 强制控制 |
| --- | --- |
| 任意代码执行 | 从不执行导入包中的脚本；不支持上传运行时插件。 |
| 供应链攻击 | ZIP 结构、路径、哈希、大小、文件类型、脚本和敏感内容扫描；导入后仍须管理员映射和发布。 |
| SSRF/网络探测 | HTTP 只允许预注册服务、固定方法和受限路径模板；禁止用户/Skill 包提供完整 URL。 |
| 凭据泄露 | 凭据仅以服务端加密引用保存；响应、审计、日志、导入和导出均脱敏。 |
| SQL 注入/越权 | 只读、预审核、参数化模板；无自由 SQL；每次执行带租户/用户上下文。 |
| 越权使用 Skill | 前端过滤与后端逐次角色校验双重执行。 |
| 高风险误操作 | 用户必须主动选择、填写并点击执行；第一阶段不做模型自动调用。 |
| 敏感结果扩散 | 字段脱敏、最大结果限制、对象存储隔离、下载时二次鉴权与短时链接。 |
| 资源耗尽 | Operation 级超时上限、并发上限、限流、队列隔离、取消和幂等控制。 |
| 审计不可追溯 | 版本、用户、角色、输入/输出摘要、执行状态和请求 ID 均写入审计。 |

安全事件优先级高于可用性：当连接器、权限、凭据、输入安全或审计持久化发生故障时，执行必须失败关闭（fail closed），不得降级为未审计调用。

## 8. 状态机

### 8.1 Skill

```text
DRAFT → PUBLISHED → DISABLED → PUBLISHED
  │          │          │
  └────────→ ARCHIVED ←┘
```

- `DRAFT`：仅管理员可见、可编辑、不可执行。
- `PUBLISHED`：当前可执行版本；需满足授权和连接器条件。
- `DISABLED`：暂时不可执行、不可在 Chat 中展示；历史保留。
- `ARCHIVED`：不可恢复为可执行；仅保留历史和导出审计。

发布一个新版本时：新版本变为 `PUBLISHED`，前当前版本变为 `SUPERSEDED`。已启动的执行继续使用其创建时锁定的版本。

### 8.2 SkillExecution

```text
PENDING → VALIDATING → QUEUED → RUNNING → SUCCEEDED
                   │         │         ├→ FAILED
                   │         │         ├→ TIMED_OUT
                   │         │         └→ CANCELED
                   └────────→ REJECTED
```

- `REJECTED`：权限、状态、输入或安全策略校验未通过；不调用连接器。
- `CANCELED`：仅在 Connector Operation 支持取消时发生；取消请求和最终状态均须审计。
- `FAILED`、`TIMED_OUT`：保留可安全显示的错误码和建议；底层敏感信息仅进入受限诊断日志。

## 9. API 设计

所有 API 位于 `/api/v1`，返回项目既有的错误结构和请求 ID。

### 9.1 用户侧 API

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/skill-categories/available` | `SKILL_READ` | 当前用户可见的分类及 Skill 数量。 |
| `GET` | `/skills/available` | `SKILL_READ` | 当前用户可执行的 Skill；支持 `category_id` 筛选。 |
| `GET` | `/skills/{skill_id}/available-definition` | `SKILL_READ` | 返回展示说明、表单 schema 和安全限制；不返回连接器内部信息。 |
| `POST` | `/chat/sessions/{session_id}/skill-runs` | `CHAT_WRITE` + `SKILL_EXECUTE` | 创建指定 Skill 的执行并返回 SSE 流。 |
| `GET` | `/skill-executions/{execution_id}` | 所有者或审计权限 | 查询状态和安全结果摘要。 |
| `POST` | `/skill-executions/{execution_id}/cancel` | 所有者或管理员 | 请求取消。 |
| `POST` | `/skill-executions/{execution_id}/retry` | 所有者且策略允许 | 基于原输入创建新的执行。 |
| `GET` | `/skill-artifacts/{artifact_id}/download` | 产物权限 | 二次鉴权后重定向至短时下载 URL。 |

`POST /chat/sessions/{session_id}/skill-runs` 请求体固定包含 `skill_id` 和结构化 `input`；服务端自行决定当前发布版本和 Connector Operation，客户端不能传 `skill_version_id`、`connector_key`、`operation_key` 或角色。

### 9.2 管理侧 API

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| CRUD | `/skill-categories` | `SKILL_CATEGORY_MANAGE` | 分类管理。 |
| CRUD | `/skills` | `SKILL_MANAGE` | Skill 基本资料和生命周期管理。 |
| `POST` | `/skills/{skill_id}/versions` | `SKILL_MANAGE` | 创建草稿版本。 |
| `POST` | `/skills/{skill_id}/versions/{version_id}/validate` | `SKILL_MANAGE` | 校验 schema、连接器映射和安全策略。 |
| `POST` | `/skills/{skill_id}/versions/{version_id}/test-runs` | `SKILL_MANAGE` | 受控测试执行。 |
| `POST` | `/skills/{skill_id}/versions/{version_id}/publish` | `SKILL_MANAGE` | 发布版本。 |
| `POST` | `/skills/{skill_id}/disable` | `SKILL_MANAGE` | 停用 Skill。 |
| `POST` | `/skills/imports` | `SKILL_MANAGE` | 上传并预检包。 |
| `POST` | `/skills/imports/{import_id}/apply` | `SKILL_MANAGE` | 选择冲突策略、映射操作，创建草稿。 |
| `GET` | `/skills/{skill_id}/export` | `SKILL_MANAGE` | 导出安全包。 |
| CRUD | `/skill-connectors` | `SKILL_CONNECTOR_MANAGE` | 租户连接配置和健康检查。 |
| `GET` | `/skill-audit-events` | `SKILL_AUDIT_READ` | 导入、管理和执行审计。 |

### 9.3 SSE 事件

Skill 执行流使用既有 Chat SSE 传输，并新增事件：

| 事件 | 最小字段 | 用途 |
| --- | --- | --- |
| `skill_run_started` | `executionId`, `skillId`, `version` | 已创建且通过基本验证。 |
| `skill_run_status` | `executionId`, `status`, `label` | 状态或阶段变化。 |
| `skill_run_progress` | `executionId`, `percent?`, `message` | 安全的进度信息。 |
| `skill_run_result` | `executionId`, `summary`, `data?` | 最终结果摘要或结构化数据。 |
| `skill_run_artifact` | `executionId`, `artifactId`, `fileName` | 已生成的受控产物。 |
| `skill_run_error` | `executionId`, `code`, `message`, `retryable` | 可安全展示的失败信息。 |
| `skill_run_done` | `executionId`, `status`, `durationMs` | 终态。 |

## 10. 前端信息架构

### 10.1 管理后台

新增一级导航“Skills”，包含：

1. **Skills 列表**：筛选、状态、版本、授权角色、调用统计；
2. **分类管理**：分类 CRUD 和排序；
3. **Skill 编辑器**：基本资料、连接器操作、输入表单、安全策略、角色、版本和发布；
4. **导入/导出**：预检报告、冲突处理、连接器映射和导入历史；
5. **连接器**：受限于高权限管理员；
6. **审计**：执行、导入、发布和授权变更记录。

### 10.2 Chat

在既有 Chat 会话界面增加 Skills 抽屉/侧栏：

- 分类标签和当前用户可用的 Skill 卡片；
- Skill 详情面板，包含说明、权限提示、影响等级和表单；
- 执行结果卡片，包含运行状态、结果摘要、可复制结构化字段、受控文件和重试/取消动作；
- 普通模型聊天的输入框与 Skill 参数表单独立，避免用户把 Skill 参数误当自然语言消息发送。

## 11. 连接器执行契约

每个 Connector Operation 必须实现统一的服务端契约：

```python
class SkillOperation(Protocol):
    key: str
    input_schema: dict
    output_schema: dict
    side_effect_level: Literal['READ_ONLY', 'EXTERNAL_WRITE', 'FILE_WRITE']

    def validate_availability(self, context: SkillExecutionContext) -> None: ...
    def execute(self, context: SkillExecutionContext, payload: dict) -> SkillOperationResult: ...
    def cancel(self, context: SkillExecutionContext) -> None: ...
```

`SkillExecutionContext` 必须包含租户、用户、角色快照、请求 ID、取消信号、脱敏日志器和产物写入器。连接器不得从客户端参数中读取凭据、完整 URL、SQL 或操作类型；这些均由固定 Operation 的服务端配置决定。

## 12. 验收标准

### 12.1 管理与授权

1. 管理员可以创建分类、创建 Tool Skill 草稿、绑定允许的 Operation、配置参数表单和角色授权，并发布。
2. 已发布 Skill 的编辑会创建新草稿版本，历史版本和历史执行不可被修改。
3. 未授权用户既不会在可用清单中看到 Skill，也不能通过直接调用 API 执行。
4. 分类或 Skill 停用后，不可创建新执行；历史记录仍可查询。

### 12.2 导入与导出

1. 导入符合标准的 `SKILL.md` 包可生成草稿，并要求管理员确认连接器映射和角色后才能发布。
2. 包含 `scripts/`、可执行文件、路径穿越、符号链接、敏感密钥模式或超限内容的导入必须失败。
3. 导出包不含凭据、内部端点、角色名单、原始执行输入、结果或审计记录。
4. 同名 Skill 导入不会静默覆盖；必须明确处理冲突。

### 12.3 执行与 Chat

1. 用户可以在现有 Chat 会话内按分类选择本人有权限的 Skill，填写表单后手动执行。
2. 执行过程中浏览器收到状态 SSE；成功、失败、超时、取消均可在结果卡片中清晰显示。
3. 后端记录执行的用户、角色快照、Skill 版本、连接器操作、参数摘要、结果摘要、请求 ID、状态和耗时。
4. 连接器输出的敏感字段不会进入 Chat、普通日志或导出包。
5. 长耗时任务可取消，超时会终止或标记为超时，且不泄露底层诊断细节。

### 12.4 安全

1. 任意 Skill 包都无法在应用服务器上执行包内代码。
2. 内部 HTTP Skill 不能被用户输入的完整 URL 驱动，不能访问非白名单目标。
3. 数据库 Skill 无法提交自由 SQL，且只有预审核的只读模板可运行。
4. 当权限、审计记录写入、连接器状态或凭据校验失败时，执行必须失败关闭。

## 13. 开发路线图

### 阶段 0：设计冻结与安全基线

- 确认本设计中的数据模型、权限矩阵、状态机和 API 契约；
- 明确连接器抽象、导入扫描规则、凭据保存方式、审计格式和威胁模型；
- 列出首批 Connector Operation 及各自的安全准入标准。

**退出条件：** 任意脚本执行、任意 URL、自由 SQL、包内凭据均被明确排除且具有测试策略。

### 阶段 1：基础管理域

- 新建分类、Skill、SkillVersion、授权、导入和审计的数据库迁移；
- 新增权限和默认管理员权限种子；
- 实现分类 API、Skill CRUD、草稿/发布/停用/归档、版本管理；
- 实现包解析、预检、冲突处理和安全导出；
- 实现管理端列表、编辑器和导入页。

**退出条件：** 管理员可安全管理一个尚未执行的 Tool Skill，且 API 和界面均能正确执行角色限制。

### 阶段 2：受控连接器和执行引擎

- 建立 Connector/Operation 注册表和统一执行契约；
- 实现输入 schema 校验、执行状态、队列任务、取消、重试、超时、产物和审计；
- 依次接入 `knowledge-base`、`database-readonly`、`internal-http`、`file-processing` 和 `ticketing` 的首批受控操作；
- 增加健康检查、限流、并发控制、脱敏和指标。

**退出条件：** 每类连接器至少有一个端到端可执行的 Skill，并覆盖权限、非法输入、超时和连接器故障测试。

### 阶段 3：Chat 集成

- 增加当前用户可用 Skill API；
- 实现 Chat Skills 抽屉、分类筛选、详情、动态表单和运行卡片；
- 将 SkillExecution 和 ChatMessage 关联，并扩展 SSE 客户端解析；
- 实现取消、允许时重试、产物下载和可访问性/移动端适配。

**退出条件：** 用户可在同一 Chat 会话完成一次被授权的查询或导出，并查看完整、安全的运行结果。

### 阶段 4：安全验收与上线治理

- 完成单元、集成、端到端、RBAC 矩阵和 SSE 测试；
- 执行恶意包、压缩炸弹、路径穿越、脚本、密钥、SSRF、SQL 注入、越权、敏感输出和资源耗尽测试；
- 完成审计页面、连接器监控、灰度发布、停用开关、回滚和事故预案。

**退出条件：** 安全验收通过，所有关键管理和执行动作均可审计，连接器异常不影响普通 Chat。

### 阶段 5：Prompt Skill（第二期）

- 开放 `PROMPT` 类型的 Skill；
- 增加提示词模板、变量、模型策略、知识库范围、引用规则和结构化输出；
- 沿用版本、角色授权、导入导出和审计；
- 如需与 Tool Skill 协同，默认仍要求用户显示确认任何工具调用。

**退出条件：** 管理员可安全发布专业 Prompt Skill，用户可按角色在 Chat 中手动调用，且模型调用与引用可追溯。

## 14. 实施范围拆分结论

本设计将一阶段分为“管理域、受控执行、Chat 集成、安全上线”四个可独立验证的交付序列。所有一阶段基础表和 API 均预留 `PROMPT` 类型和共享的版本/权限/审计结构，但不实现 Prompt 的编辑器、编排或运行时。这一拆分避免二阶段破坏性迁移，同时把首期风险集中在安全连接器和可审计执行上。
