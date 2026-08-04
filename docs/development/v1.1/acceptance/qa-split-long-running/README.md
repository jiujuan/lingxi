# QA Split Long-Running Acceptance

## Task 14

本目录归档 QA Split 长耗时治理的端到端验收证据。自动化 fixture 覆盖：

- 上传 Markdown fixture 后执行 Parse -> QA Split -> Embedding；
- 慢模型成功返回后最终进入 `READY`；
- 首批 6 Chunk 发生读取超时后按 `3 + 3` 二分并成功完成；
- `items: {}` 结构错误只调用一次，并保留既有 `ACTIVE` QA；
- ModelCallLog、QaSplitRun、QaSplitBatch、QaPair 的顺序和最终状态；
- 管理端桌面和移动端配置、连接诊断、模型调用详情和无水平溢出。

### 运行命令

```powershell
pytest server/tests/e2e/test_v1_1_release_e2e.py -q

$env:LINGXI_ACCEPTANCE_SCREENSHOT_PREFIX='task-14-screenshot'
python web/admin/tests/t19_qa_split_timeout_playwright.py
```

验收结果记录在 `task-14-run.json`；脱敏的模型调用记录记录在
`task-14-model-call-log.json`；浏览器截图为：

- `task-14-screenshot-desktop.png`
- `task-14-screenshot-mobile.png`

### Fixture 参数和边界

| Fixture | Provider / model | Timeout | Batch / retry / split | 最终状态 |
| --- | --- | --- | --- | --- |
| slow-success | 注入的 `FixtureQaProvider` / `fixture-qa-slow` | 约 30 ms 模拟读取延迟；记录非零延迟成功 | 2 Chunk；`maxRetries=0`；`maxSplitDepth=1` | Document `READY`，ImportJob `COMPLETED` |
| timeout-split-recovery | 注入的 `FixtureQaProvider` / `fixture-qa-split` | `PROVIDER_INFERENCE_TIMEOUT`，phase=`read`，`timeoutMs=240000` | 初始 6 Chunk；`maxRetries=0`；二分为 `3 + 3` | Document `READY`，6 个 `QaPair` |
| invalid-items-terminal | 注入的 invalid-output provider / `fixture-invalid-output` | 不适用 | `items` 为对象；即使 `maxRetries=2` 也不重试 | Document `FAILED`，错误码 `QA_PROVENANCE_CONTRACT_INVALID`，既有 `ACTIVE` QA 保留 |

### 证据边界

本环境使用可重复的注入式慢模型和错误模型完成自动化验收。真实 Ollama Gemma
和 DeepSeek Provider 需要外部服务、模型和凭据；本次没有伪造或声称已经完成真实
Provider 调用，因此真实模型的运行证据不包含在本目录中。

所有证据均不记录 API Key、完整 Prompt、完整模型输出或 PDF 原文。截图中的
Provider endpoint 使用测试域名，ModelCallLog 仅保留诊断字段。

验收日期：`2026-08-04`
