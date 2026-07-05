# T03 文档数据模型与权限过滤 Repository

## 任务状态

- 状态：IN_PROGRESS
- 完成任务进度：80%
- 优先级：P0
- 预计范围：中

## Task 目标

实现 V1.1 文档、文档权限、导入任务、Chunk、QA 对、Chat、引用、日志相关核心数据表和 Repository，并完成文档级 RBAC 的 SQL 前置过滤。

## 实现功能

- `documents`、`document_access_rules`、`import_jobs`、`import_job_files`。
- `parse_artifacts`、`document_chunks`、`qa_pairs`。
- `chat_sessions`、`chat_messages`、`query_runs`、`query_citations`、`missed_questions`。
- `task_runs`、`audit_logs`、`system_settings` 基础表。
- pgvector 扩展、QA 向量列和全文检索字段。
- 文档授权查询 Repository。
- 软删除和分页查询约束。

## 修改或增加文件

- `server/app/models/document.py`
- `server/app/models/import_job.py`
- `server/app/models/qa_pair.py`
- `server/app/models/chat.py`
- `server/app/models/logs.py`
- `server/app/repositories/document_repository.py`
- `server/app/repositories/import_job_repository.py`
- `server/app/repositories/qa_pair_repository.py`
- `server/app/repositories/retrieval_repository.py`
- `server/app/db/migrations/versions/*_documents_core.py`

## 不修改范围

- 不实现上传 API。
- 不实现 Worker 解析和 QA 拆分。
- 不实现 Chat 业务逻辑。
- 不引入独立向量数据库。

## 涉及其它 Task

- 依赖 T01、T02。
- T05-T08 写入这些表。
- T10 使用授权检索 Repository。

## 测试策略

- Alembic migration 从空库执行测试。
- 文档访问规则 Repository 单元测试。
- 不同部门、角色、用户授权检索测试。
- pgvector 写入和查询 smoke test。
- tsvector 生成和查询 smoke test。

## 长任务链路验收策略

构造两个用户和两份不同权限文档，写入 QA 对后执行授权查询，确认用户只能拿到自己有权访问的 QA 对。

## 验收功能清单

- [x] 核心表迁移成功。
- [x] pgvector 扩展在 PostgreSQL migration 中启用。
- [x] QA 向量字段在 ORM 和 PostgreSQL migration 中定义。
- [x] QA 全文检索字段和 PostgreSQL GIN 索引在 migration 中定义。
- [x] 文档权限规则支持部门、角色、用户、全部登录用户。
- [x] Repository 默认排除软删除和非 READY 文档数据。
- [x] 授权查询安全测试通过。
- [ ] pgvector 和 tsvector 需在真实 PostgreSQL + pgvector 环境做 smoke test。

## 验收结果

- 已实现文档、权限规则、导入任务、解析产物、Chunk、QA 对、Chat、引用、任务日志、审计日志、系统设置等核心模型。
- 已实现 baseline migration，并在 SQLite 内存库完成从空库执行验证。
- 已实现 `DocumentRepository.list_authorized_qa_pairs`，在 SQL 查询阶段按部门、角色、用户和全部登录用户过滤，同时排除软删除和非 READY 文档。
- 验证通过：`python -m pytest server\tests\test_document_permissions.py`，1 passed。
- 未完成实机验收：当前环境未安装 Docker CLI，真实 PostgreSQL + pgvector 的向量索引和 tsvector smoke test 待补。

## 完成任务进度

80%
