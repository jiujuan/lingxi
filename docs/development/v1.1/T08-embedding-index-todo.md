# T08 Embedding、全文索引与文档 READY 状态

## 任务状态

- 状态：DONE
- 完成任务进度：100%
- 优先级：P0
- 预计范围：中

## Task 目标

实现 QA question 的 Embedding、全文检索 search_text/search_vector 写入、向量维度校验、索引完成状态更新，让文档从 QA_SPLITTING/EMBEDDING 进入 READY 并可被检索。

## 实现功能

- EmbeddingProvider 调用封装。
- `embed_qa_pairs_task`。
- 批量生成 `qa_pairs.question_embedding`。
- 中文分词生成 `search_text`。
- Embedding 维度校验。
- Embedding 失败记录和单独重试。
- 文档 `qa_pair_count`、`chunk_count` 统计更新。
- 文档状态更新为 READY。

## 修改或增加文件

- `server/app/tasks/embedding_tasks.py`
- `server/app/services/embedding_service.py`
- `server/app/integrations/tokenizers/base.py`
- `server/app/integrations/tokenizers/jieba_tokenizer.py`
- `server/app/repositories/qa_pair_repository.py`
- `server/app/repositories/document_repository.py`
- `server/app/tests/worker/test_embedding_task.py`
- `server/app/tests/integration/test_qa_pair_indexes.py`

## 不修改范围

- 不实现向量检索排序算法。
- 不实现 Chat 回答。
- 不支持同一向量列混用不同 Embedding 维度。

## 涉及其它 Task

- 依赖 T04、T07。
- T09 展示 READY 状态和 Embedding 失败重试。
- T10 使用向量和全文索引检索。

## 测试策略

- fake embedding provider 返回固定维度向量。
- 维度不匹配失败测试。
- 批量写入向量测试。
- search_text 生成测试。
- READY 状态更新测试。
- Embedding 重试幂等测试。

## 长任务链路验收策略

对已有 QA 对执行 embedding task，写入 question_embedding 和 search_text，确认 pgvector/tsvector 查询可命中，文档状态更新为 READY。

## 验收功能清单

- [x] Embedding task 可批量处理 QA 对。
- [x] 向量维度校验可用。
- [x] question_embedding 写入成功。
- [x] search_text/search_vector 可用于全文检索。
- [x] Embedding 失败可单独重试。
- [x] 文档 READY 状态更新正确。
- [x] 重试不重复生成 QA 对。

## 验收结果

- 已实现 EmbeddingProvider mock 调用封装和 `EmbeddingService`。
- 已实现 `embed_qa_pairs_task`，并在 QA task 成功后衔接 Embedding 队列。
- 已实现批量写入 `qa_pairs.question_embedding`、`search_text` 和 token 统计。
- 已实现 CJK/英数稳定分词器，作为 `jieba_tokenizer.py` 的 MVP 替换点。
- 已实现向量维度校验；维度不匹配时记录失败并将 QA 对标记为 `EMBEDDING_FAILED`。
- 已实现文档统计和状态更新：`qa_pair_count`、`chunk_count`、`documents.status=READY`、`import_jobs.status=COMPLETED`。
- 验证结果：`python -m pytest server\tests\test_embedding_task.py` 通过；后端全量测试通过；Alembic 基线烟测通过。

## 完成任务进度

100%
