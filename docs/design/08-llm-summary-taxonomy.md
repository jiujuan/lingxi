# T08 LLM 摘要、类别与标签

## 状态

- 状态：DONE
- 完成任务进度：100%
- 优先级：P0
- 预计范围：大

## Task 目标

实现文章摘要和分类链路：根据 article Markdown 调用 LLM provider，生成结构化 JSON，校验并写入 `article_summaries`、`categories`、`tags` 和 `article_tags`。失败不阻塞文章入库。

## 实现功能

- LLM provider 配置读取。
- Provider 路由和 fallback。
- DeepSeek、Agnes、Ollama、qwen provider 适配。
- Prompt builder。
- Summary JSON schema validation。
- tag 归一化和最多 15 个约束。
- category 选择或建议。
- 摘要补跑。
- LLM provider 测试 API。

## 修改或增加功能函数和文件

LLM：

- `server/llm/types.py`
  - `SummaryRequest`
  - `SummaryResult`
  - `DailyReportRequest`
  - `DailyReportResult`
- `server/llm/prompts.py`
- `server/llm/router.py`
- `server/llm/deepseek.py`
- `server/llm/agnes.py`
- `server/llm/ollama.py`
- `server/llm/qwen.py`
- `server/llm/validators.py`
  - `validate_summary_result()`
  - `validate_tag_limit()`

Services/API：

- `server/services/summary_service.py`
  - `summarize_article()`
  - `build_summary_request()`
  - `validate_summary_result()`
  - `apply_summary()`
- `server/services/llm_service.py`
- `server/services/category_service.py`
- `server/services/tag_service.py`
- `server/router/articles.py`
- `server/router/categories.py`
- `server/router/tags.py`
- `server/router/llm.py`

Workers/tests：

- `server/workers/summary_tasks.py`
- `server/tests/unit/test_summary_validator.py`
- `server/tests/unit/test_tag_normalization.py`
- `server/tests/unit/test_llm_router.py`
- `server/tests/integration/test_summary_api.py`
- `server/tests/integration/test_llm_provider_config_api.py`

## 不修改范围

- 不生成日报，交给 T09。
- 不实现前端文章详情和 LLM 设置页面。
- 不把网页正文中的指令作为 system prompt。
- 不保存 API key 明文，只保存密钥引用。

## 涉及其它 Task

- 依赖 T02、T07。
- T09 使用 summary 结果生成日报。
- T10 读取 summary 失败状态。
- T13 展示摘要、类别、标签和 LLM 设置。

## 测试策略

- 使用 fake provider 返回固定 JSON。
- validator 覆盖缺失 highlight、tag 超过 15、importanceScore 越界、非法 JSON。
- summary task 测试失败重试和 `summary_status` 更新。
- API 测试 `/articles/{id}/summarize` 和 `/llm/test`。

## 长任务链路验收策略

验收“Article To Summary”链路：准备 article -> enqueue summary -> fake provider 返回 JSON -> validator -> 写 `article_summaries` -> upsert category/tag/article_tags -> article detail 能返回摘要和 tags。

## 验收功能清单

- [x] 支持 deepseek、agnes、ollama、qwen provider 配置。
- [x] LLM 输出必须是结构化 JSON。
- [x] `highlight_1/2/3` 必填。
- [x] tag 最多 15 个。
- [x] `importance_score` 在 0..1。
- [x] 摘要失败不回滚 article。
- [x] `/tags/normalize` 可归一 tag。

## 验收结果

- 新增 `server/llm` provider contract、fake provider、deepseek/agnes/ollama/qwen 适配入口、prompt builder 和 summary validator。
- `server/services/summary_service.py` 已实现 article -> summary 的同步补跑链路：构建请求、调用 provider、写入 `article_summaries`、upsert category/tag、写入 `article_tags`，并更新 `Article.summary_status`。
- `server/services/tag_service.py` 支持 tag slug 归一、去重和最多 15 个约束；`/api/v1/tags/normalize` 已接入。
- `/api/v1/articles/{articleId}/summarize` 已接入 fake provider，可返回包含 `summary`、`category`、`tags` 的 Article 详情。
- `/api/v1/llm/providers` 支持 provider 配置 upsert/list；写入接受 `apiKeyRef`，响应只返回 `hasApiKeyRef`，不回显密钥引用或明文。
- `/api/v1/llm/test` 可用 fake provider 做 provider contract smoke。
- 摘要失败会写 `summary_status=failed` 和 `article_summaries.status=failed`，不会删除或回滚 article。
- 验证命令：
  - `python -m pytest server\tests -q`：83 passed。
  - `npm run typecheck`：passed。
  - `npm run build`：passed。

## 完成任务进度

100%
