# T05 文档上传任务与对象存储

## 任务状态

- 状态：DONE
- 完成任务进度：100%
- 优先级：P0
- 预计范围：中

## Task 目标

实现知识库文档上传的第一段闭环：创建导入任务、设置权限、校验文件、写入对象存储、绑定导入文件、查询任务状态，为后续解析 Worker 提供稳定输入。

## 实现功能

- ObjectStorageAdapter local/minio 基础实现。
- 创建 `import_jobs` 和 `documents`。
- 上传前后端文件类型、大小、数量校验。
- 文档权限范围写入 `document_access_rules`。
- 文件上传或对象绑定接口。
- 任务状态查询接口。
- 重复文件 checksum 检测。
- 上传和权限变更审计日志。
- 前端上传页任务创建、权限选择和状态轮询。

## 修改或增加文件

- `server/app/integrations/storage/base.py`
- `server/app/integrations/storage/local.py`
- `server/app/integrations/storage/minio.py`
- `server/app/services/import_service.py`
- `server/app/services/document_service.py`
- `server/app/api/v1/import_jobs.py`
- `server/app/api/v1/documents.py`
- `server/app/schemas/import_job.py`
- `web/admin/src/features/knowledge/pages/ImportPage.tsx`
- `web/admin/src/features/knowledge/components/ImportJobTimeline.tsx`

## 不修改范围

- 不实现文档解析 Worker。
- 不实现 QA 拆分和 Embedding。
- 不实现文档详情全部 UI。
- 不物理删除对象存储文件。

## 涉及其它 Task

- 依赖 T03。
- T06 读取本任务保存的原文件。
- T09 展示上传和任务状态。
- T15 展示任务日志。

## 测试策略

- 文件类型和大小校验测试。
- local storage put/stat/get 测试。
- 创建导入任务 API 测试。
- 绑定文件 API 测试。
- 权限规则写入测试。
- 前端上传页表单测试。

## 长任务链路验收策略

管理员选择样本文档，设置部门/角色权限，创建导入任务并上传文件，前端可轮询到任务状态，数据库存在 document、access rules、import job 和 import job file。

## 验收功能清单

- [x] 可创建导入任务。
- [x] 可上传或绑定文件。
- [x] 文件类型、大小、数量校验可用。
- [x] 文档权限规则随上传写入。
- [x] 原文件 object_key 安全保存。
- [x] checksum 重复提示可用。
- [x] 上传操作写审计日志。
- [x] 前端上传页可展示任务状态。

## 验收结果

- 已实现 local ObjectStorageAdapter，并保留 MinIO adapter 入口；V1.1 本地开发和测试使用 local storage。
- 已实现 `/api/v1/import-jobs`、`/api/v1/import-jobs/{jobId}/files`、`/api/v1/import-jobs/{jobId}`。
- 已实现导入任务创建、文档占位对象、访问规则写入、文件绑定、文件类型/大小/数量校验、object_key 防路径穿越、checksum 重复检测、审计日志和解析任务入队入口。
- 已实现前端知识导入基础页面：创建任务、选择 Markdown/TXT 文件、绑定文件、展示任务状态并轮询。
- 验证结果：`python -m pytest server\tests\test_import_jobs.py` 通过，前端 `npm run build` 通过。

## 完成任务进度

100%
