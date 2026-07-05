# T04 模型供应商配置与连接测试

## 任务状态

- 状态：DONE
- 完成任务进度：100%
- 优先级：P0
- 预计范围：中

## Task 目标

实现模型供应商和模型实例配置能力，支持 OpenAI 兼容、Claude、Ollama、内部网关的 Adapter contract、密钥加密存储、默认模型设置和连接测试。

## 实现功能

- `model_providers`、`model_configs`、`model_call_logs` 模型和迁移。
- ChatProvider、EmbeddingProvider 基类。
- OpenAI compatible、Claude、Ollama、internal gateway adapter 入口。
- fake provider 用于测试。
- 模型供应商 CRUD API。
- 模型实例 CRUD API。
- 默认 Chat、Embedding、QA Split 模型设置。
- 连接测试接口和模型调用日志。
- Secret 保存后不回显。
- 前端模型配置页基础功能。

## 修改或增加文件

- `server/app/models/model_config.py`
- `server/app/integrations/model_providers/base.py`
- `server/app/integrations/model_providers/openai_compatible.py`
- `server/app/integrations/model_providers/claude.py`
- `server/app/integrations/model_providers/ollama.py`
- `server/app/services/model_config_service.py`
- `server/app/api/v1/model_config.py`
- `server/app/schemas/model_config.py`
- `web/admin/src/features/model-config/pages/ModelConfigPage.tsx`
- `web/admin/src/features/model-config/api/modelConfigApi.ts`

## 不修改范围

- 不实现完整 QA 拆分、Embedding、Chat 业务链路。
- 不要求真实外部模型在测试环境可用。
- 不保存模型 API Key 明文。

## 涉及其它 Task

- 依赖 T02、T03。
- T07 使用 QA Split 模型。
- T08 使用 Embedding 模型。
- T11 使用 Chat 模型。

## 测试策略

- fake provider contract 测试。
- 连接测试成功/失败测试。
- Secret 不回显测试。
- 默认模型唯一性测试。
- 前端模型配置表单测试。

## 长任务链路验收策略

管理员创建 fake/OpenAI compatible 供应商，新增 Chat 和 Embedding 模型，执行连接测试，设置默认模型，前端只看到 `secretConfigured=true`。

## 验收功能清单

- [x] 模型供应商表和模型配置表迁移成功。
- [x] Provider Adapter contract 可用。
- [x] 供应商创建和编辑接口可用。
- [x] 连接测试接口可用。
- [x] 默认模型设置可用。
- [x] 模型密钥不明文返回。
- [x] 模型调用日志记录 request_id、耗时和错误码。
- [x] 前端模型配置页可完成基础操作。

## 验收结果

- 已实现 `model_providers`、`model_configs`、`model_call_logs` 模型，接入 `/api/v1/model-providers` 和 `/api/v1/model-configs`。
- 已实现 OpenAI Compatible、Claude、Ollama、Internal Gateway adapter 入口；当前连接测试支持 mock/config-level 校验，不在测试环境访问真实外部模型。
- 已实现模型密钥密文封装存储，API 响应只返回 `secretConfigured`。
- 已实现默认模型唯一性控制和模型调用日志。
- 已实现前端模型配置基础页面：供应商创建、连接测试、模型实例创建、设为默认。
- 验证结果：`python -m pytest server\tests\test_model_config.py` 通过，前端 `npm run build` 通过。

## 完成任务进度

100%
