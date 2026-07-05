# T10 混合检索与轻量 ReRank 引擎

## 任务状态

- 状态：DONE
- 完成任务进度：100%
- 优先级：P0
- 预计范围：中

## Task 目标

实现可被 Chat 和 OpenAI 兼容 API 复用的检索引擎，在 SQL 阶段完成权限前置过滤，并通过 pgvector、PostgreSQL 全文检索、RRF 融合和纯代码 ReRank 返回可解释的 Top 引用候选。

## 实现功能

- `RetrievalService` 统一入口。
- Query Embedding 生成。
- 向量召回 TopK，使用 `qa_pairs.question_embedding`。
- 全文召回 TopK，使用 `qa_pairs.search_vector`。
- SQL 前置权限过滤，基于用户、部门、角色和 API Key 权限范围。
- RRF 融合向量召回和全文召回。
- 轻量 ReRank 特征：RRF 基础分、精确命中、标题相似度、位置加权。
- 低置信度阈值判断。
- 检索快照结构，记录候选、分数、过滤原因和耗时。
- 内部检索调试接口或 service-level 测试入口。
- 未命中问题写入 `missed_questions` 的基础能力。

## 修改或增加文件

- `server/app/services/retrieval_service.py`
- `server/app/services/rerank_service.py`
- `server/app/repositories/retrieval_repository.py`
- `server/app/repositories/missed_question_repository.py`
- `server/app/schemas/retrieval.py`
- `server/app/core/retrieval_config.py`
- `server/app/tests/services/test_retrieval_service.py`
- `server/app/tests/services/test_rerank_service.py`
- `server/app/tests/security/test_retrieval_permission_filter.py`
- `server/app/tests/integration/test_hybrid_retrieval.py`

## 不修改范围

- 不实现 Chat SSE。
- 不调用外部 ReRank 模型。
- 不引入 Elasticsearch、OpenSearch、Milvus 或 Qdrant。
- 不实现 GraphRAG 或多跳图谱推理。
- 不在应用层先召回全量候选后再过滤权限。

## 涉及其它 Task

- 依赖 T08 的 Embedding、全文索引和 READY 状态。
- 使用 T02/T03 的用户、角色、部门和文档权限数据。
- T11 使用本任务输出候选构造回答。
- T12 使用本任务的检索快照展示检索解释。
- T14 复用本任务作为 OpenAI 兼容 API 的检索能力。
- T17 对本任务做权限安全和性能回归。

## 测试策略

- 构造向量命中、全文命中、两路融合的固定数据集。
- 测试只有向量结果、只有全文结果、两路都无结果的边界场景。
- 测试 RRF 排序稳定性。
- 测试轻量 ReRank 各特征加权结果。
- 测试低置信度触发知识不足。
- 测试不同部门、角色、用户只能召回有权限 QA 对。
- 测试 API Key 权限范围不会越权召回。
- 使用 EXPLAIN 或集成测试检查检索查询命中关键索引。

## 长任务链路验收策略

准备 3 份 READY 文档，分别授予不同部门和角色。以不同用户身份提交同一问题，确认 SQL 查询只返回当前用户有权访问的候选；再验证向量召回、全文召回、RRF、ReRank 四阶段快照完整，低置信问题写入 missed_questions。

## 验收功能清单

- [x] Query Embedding 可生成并参与向量检索。
- [x] pgvector TopK 召回可用。
- [x] PostgreSQL 全文召回可用。
- [x] 权限过滤发生在 SQL 阶段。
- [x] RRF 融合排序可用。
- [x] 轻量 ReRank 不依赖外部模型。
- [x] 低置信度问题能返回知识不足状态。
- [x] 检索快照包含向量、全文、RRF、ReRank 四阶段信息。
- [x] 未命中问题能记录 request_id 和问题摘要。
- [x] 权限安全测试覆盖部门、角色、用户和 API Key 范围。

## 验收结果

- 已完成。
- 后端验证：`python -m pytest server\tests`，结果 `45 passed`。
- T10 定向验证：`server/tests/test_retrieval_service.py`、`server/tests/test_rerank_service.py` 覆盖混合检索、RRF、轻量 ReRank、低置信 missed question、部门权限和 API Key scope 交集过滤。
- 说明：生产 PostgreSQL 仍沿用 T08 已创建的 pgvector HNSW 索引和 `search_vector` GIN 索引；SQLite 测试环境使用兼容的 Python 评分路径验证业务行为。

## 完成任务进度

100%
