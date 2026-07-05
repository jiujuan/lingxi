# T07 QA 拆分 Worker 与 QA 对管理

## 任务状态

- 状态：DONE
- 完成任务进度：100%
- 优先级：P0
- 预计范围：中

## Task 目标

实现基于解析文本和 Chunk 的 QA 拆分链路，调用默认 QA Split 模型生成问题-答案对，保留原文引用、页码和 Chunk 关系，并支持失败重试和重新生成。

## 实现功能

- QA split prompt builder。
- QA split 输出 JSON schema validation。
- `split_document_qa_task`。
- `qa_pairs` 写入 question、answer、quote、page_no、chunk_id。
- QA 拆分失败错误记录。
- 重新生成 QA 对接口。
- QA 对列表接口。
- 任务幂等：同一 job 重试不重复写 QA 对。

## 修改或增加文件

- `server/app/services/qa_split_service.py`
- `server/app/services/qa_prompt_builder.py`
- `server/app/tasks/qa_tasks.py`
- `server/app/schemas/qa_pair.py`
- `server/app/api/v1/qa_pairs.py`
- `server/app/api/v1/documents.py`
- `server/app/repositories/qa_pair_repository.py`
- `server/app/tests/unit/test_qa_split_validator.py`
- `server/app/tests/worker/test_qa_split_task.py`

## 不修改范围

- 不实现 Embedding。
- 不实现最终 Chat 回答。
- 不人工编辑 QA 对内容。
- 不把模型输出未经校验直接入库。

## 涉及其它 Task

- 依赖 T04、T06。
- T08 对 QA question 生成 Embedding。
- T09 展示 QA 对。
- T10 检索 QA 对。

## 测试策略

- fake provider 返回固定 QA JSON。
- validator 覆盖非法 JSON、缺失 question/answer、页码缺失。
- QA task 成功和失败测试。
- QA 重新生成幂等测试。
- QA 对列表分页测试。

## 长任务链路验收策略

对已解析文档执行 QA task，fake provider 返回 QA JSON，系统校验并写入 qa_pairs，文档状态进入 EMBEDDING，失败时保留 Chunk 并允许重试。

## 验收功能清单

- [x] QA prompt builder 可用。
- [x] QA 输出 schema 校验可用。
- [x] QA task 可生成 QA 对。
- [x] QA 对包含文档、Chunk、页码、原文片段。
- [x] QA 失败不删除解析产物。
- [x] QA 重新生成接口可用。
- [x] QA 重试不重复写入。

## 验收结果

- 已实现 `qa_prompt_builder`、QA 输出 JSON schema 校验和 `QaSplitService`。
- 已实现 `split_document_qa_task`，并在 parse task 成功后衔接 QA 队列。
- 已实现 QA 对幂等写入：同一文档重新拆分会替换旧 QA 对，不重复累加。
- 已实现 QA 失败记录：`documents.last_error_*`、`import_jobs.error_*`、`task_runs.error`，并保留原 Chunk。
- 已实现 `/api/v1/documents/{documentId}/qa-pairs` 和 `/api/v1/documents/{documentId}/qa-regenerations`。
- 已在知识导入页补充 QA 对查看、刷新和重新生成基础入口。
- 验证结果：`python -m pytest server\tests\test_qa_split_task.py` 通过；后端全量测试通过。

## 完成任务进度

100%
