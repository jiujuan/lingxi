# T06 文档解析 Worker 与原文 Chunk

## 任务状态

- 状态：DONE
- 完成任务进度：100%
- 优先级：P0
- 预计范围：中

## Task 目标

实现异步文档解析链路：Worker 从对象存储读取原文件，通过 ParserAdapter 输出结构化文本、表格、页码和 Chunk，保存解析产物和失败原因。

## 实现功能

- ParserAdapter 基类。
- lightweight parser 支持 Markdown/TXT 简单格式。
- MinerU adapter 入口和错误归一化。
- `parse_document_task`。
- `parse_artifacts` 写入。
- `document_chunks` 写入。
- 解析阶段状态更新：PARSING、FAILED。
- 解析失败原因、错误码、可重试标记。
- 任务幂等：重复解析不产生重复 Chunk。

## 修改或增加文件

- `server/app/integrations/parsers/base.py`
- `server/app/integrations/parsers/lightweight.py`
- `server/app/integrations/parsers/mineru.py`
- `server/app/tasks/parse_tasks.py`
- `server/app/services/import_service.py`
- `server/app/services/document_parse_service.py`
- `server/app/repositories/import_job_repository.py`
- `server/app/repositories/document_repository.py`
- `server/app/tests/worker/test_parse_document_task.py`

## 不修改范围

- 不实现 QA 拆分。
- 不实现 Embedding。
- 不保证 MinerU 服务生产部署，只实现 Adapter 入口和 fake/lightweight 可测路径。

## 涉及其它 Task

- 依赖 T04、T05。
- T07 读取解析产物和 Chunk 生成 QA 对。
- T09 展示解析状态和原文片段。

## 测试策略

- lightweight parser 单元测试。
- parse task 成功写入 Chunk 测试。
- parse task 失败写入错误和任务日志测试。
- 幂等重试测试。
- object_key 安全校验测试。

## 长任务链路验收策略

上传 Markdown/TXT 样本文档后执行 parse task，任务完成后可在数据库看到 parse_artifacts 和 document_chunks，文档进入 QA_SPLITTING 前置状态。

## 验收功能清单

- [x] ParserAdapter contract 可用。
- [x] lightweight parser 可解析样本文档。
- [x] parse task 可读取对象存储文件。
- [x] parse task 可写解析产物。
- [x] parse task 可写 document_chunks。
- [x] 解析失败可记录错误码和错误摘要。
- [x] 重试不产生重复 Chunk。

## 验收结果

- 已实现 ParserAdapter contract、LightweightParser 和 MinerU adapter 入口。
- 已实现 `DocumentParseService.parse_import_job()`：读取对象存储原文件、解析 Markdown/TXT、写 `parse_artifacts`、写 `document_chunks`、更新文档和导入任务状态。
- 已实现 `parse_document_task` Celery task 入口，并在 Celery 配置中注册任务模块。
- 已实现解析失败记录：`documents.last_error_*`、`import_jobs.error_*`、`task_runs.error`。
- 已实现幂等重试：重复解析同一任务会替换旧解析产物和 Chunk，不产生重复 Chunk。
- 验证结果：`python -m pytest server\tests\test_parse_document_task.py` 通过。

## 完成任务进度

100%
