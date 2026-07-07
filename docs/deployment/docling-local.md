# 本地部署 Docling 解析服务

Lingxi 支持两个重型文档解析引擎：MinerU（见 [mineru-local.md](./mineru-local.md)）与 [Docling](https://github.com/docling-project/docling)。Docling 通过 HTTP 调用自部署的 [docling-serve](https://github.com/docling-project/docling-serve)，覆盖 PDF / Word / PPT / Excel / 图片，并**独占支持 HTML**（架构与引擎选择语义见 [07-document-parser-architecture.md §十二](../design/v1.1/07-document-parser-architecture.md)）。**Docling 是可选服务**：未配置 `DOCLING_BASE_URL` 时系统正常运行。

## 1. 部署方式选择

| 方式 | 适用场景 | 说明 |
| --- | --- | --- |
| A. pip 安装 + `docling-serve run` | 开发机（Windows/macOS/Linux），CPU 可用 | Docling 对 CPU 友好，无 GPU 也有可用速度 |
| B. Docker | 服务器部署 | 官方镜像 `quay.io/docling-project/docling-serve`，有 CPU 与 CUDA（cu128/cu130）变体 |
| C. Redis RQ 多 worker | 生产高并发 | API 进程收任务、`docling-serve rq-worker` 进程执行，水平扩展 |

与 MinerU 的选型参考：MinerU 对中文版面/公式解析更优（也是 `auto` 模式下共有格式的默认引擎）；Docling 格式覆盖更广（HTML 独占）、CPU 部署更轻。两者可同时部署，由 `DOC_PARSER_ENGINE` 决定路由。

## 2. 方式 A：pip 安装（开发机推荐）

> ⚠️ docling-serve 依赖 PyTorch 等重型包，**使用独立 Python 环境**，不要装进 Lingxi 运行环境。

```powershell
python -m venv D:\envs\docling
D:\envs\docling\Scripts\Activate.ps1

pip install --upgrade pip
pip install docling-serve -i https://mirrors.aliyun.com/pypi/simple

# 启动（默认端口 5001，与 Lingxi 8000 / MinerU 8888 不冲突）
docling-serve run --host 127.0.0.1 --port 5001
```

首次解析会自动下载布局/表格识别模型（数百 MB，缓存于用户目录）。验证：

```powershell
curl http://127.0.0.1:5001/health          # 期望 200
Start-Process http://127.0.0.1:5001/docs   # Swagger UI
```

如需鉴权，服务端设 `DOCLING_SERVE_API_KEY=<key>`，Lingxi 侧配同值的 `DOCLING_API_KEY`（以 `X-Api-Key` 头发送）。

## 3. 方式 B：Docker 部署

```bash
# CPU 版
docker run -d --name docling-serve \
  -p 5001:5001 \
  -v docling-models:/opt/app-root/src/.cache \
  quay.io/docling-project/docling-serve

# NVIDIA GPU 版（用带 CUDA 版本号的显式 tag，CUDA 镜像不提供 latest）
docker run -d --name docling-serve --gpus all \
  -p 5001:5001 \
  -v docling-models:/opt/app-root/src/.cache \
  quay.io/docling-project/docling-serve-cu130:v1.18.0
```

要点：挂载模型缓存卷避免重建容器后重新下载；生产高并发用 Redis RQ 模式（API 进程 + 至少一个 `docling-serve rq-worker`，否则任务只入队不执行），参考[官方部署文档](https://github.com/docling-project/docling-serve/blob/main/docs/deployment.md)。

## 4. 对接 Lingxi

### 4.1 配置 `.env`

```env
# 引擎选择：auto（默认）= 两个引擎都注册、MinerU 优先处理共有格式，
# Docling 只接收独占的 .html/.htm；要让 Docling 解析 PDF/Office，
# 必须显式指定 docling
DOC_PARSER_ENGINE=auto
DOCLING_BASE_URL=http://127.0.0.1:5001
# 服务端设了 DOCLING_SERVE_API_KEY 才需要
DOCLING_API_KEY=
DOCLING_TIMEOUT_MS=30000
DOCLING_MAX_WAIT_SECONDS=600
DOCLING_POLL_INTERVAL_SECONDS=3.0
```

**三处检查：**

1. `DOCLING_BASE_URL` 必须让 **API 进程和 Celery worker 都读到**，改完两者都要重启；
2. 存量 `.env` 中残留的旧 `UPLOAD_ALLOWED_EXTENSIONS` 会把新格式（含 .html）钉死在白名单之外，删掉或扩充；
3. 停用某个引擎时**同时清空其 `*_BASE_URL`**——健康探针按配置驱动，残留 URL 会让已停用引擎的探活继续参与 `/health` 的 degraded 判定。

### 4.2 验证链路

```powershell
# 1) Lingxi 健康检查应显示 docling: up（未配置时为 unconfigured）
curl http://localhost:8000/health

# 2) 包络冒烟（上线 checklist 必做）：确认异步三步与客户端 _extract_result 匹配
curl -X POST http://127.0.0.1:5001/v1/convert/file/async `
  -F "files=@sample.pdf" -F "to_formats=md" -F "to_formats=json"
# → 记下返回的 task_id，轮询状态直至 success，再取结果：
curl "http://127.0.0.1:5001/v1/status/poll/<task_id>?wait=5"
curl http://127.0.0.1:5001/v1/result/<task_id>
# 确认结果含 document.md_content 与 document.json_content

# 3) 端到端：管理后台上传一个 .html 或 PDF（engine=docling 时），
#    观察导入任务走完 PARSING → QA_SPLITTING → EMBEDDING → COMPLETED，
#    文档详情的 parser_name 应为 DOCLING
```

若步骤 2 的响应结构与预期不符（解析任务报 `PARSER_RESPONSE_INVALID`），调整点集中在 `server/app/integrations/parsers/docling.py` 的 `_extract_result()` / `_extract_task_id()`（设计上的唯一改动点）。

### 4.3 容量提示

与 MinerU 相同：一个解析任务最多占用 parse 队列 worker 槽位 `DOCLING_MAX_WAIT_SECONDS`（默认 600s），失败后 Celery 层最多再重试 3 次。RQ 多 worker 部署时注意异步任务结果有保留时限——Lingxi 客户端在轮询到 success 的同一循环内立即取结果，正常情况下不受影响。

## 5. 常见问题

| 现象 | 处理 |
| --- | --- |
| 上传 .html 仍返回 415 | `DOCLING_BASE_URL` 未被 API 进程读到（未重启）、`DOC_PARSER_ENGINE=mineru` 锁死了引擎，或 `.env` 残留旧 `UPLOAD_ALLOWED_EXTENSIONS` |
| 上传 PDF 走了 MinerU 而不是 Docling | `auto` 模式下 MinerU 优先属预期；要 Docling 处理需 `DOC_PARSER_ENGINE=docling` |
| 解析报 `PARSER_REQUEST_ERROR`（401/403） | 服务端设了 `DOCLING_SERVE_API_KEY` 但 Lingxi 未配 `DOCLING_API_KEY` |
| Lingxi `/health` 中 docling: down | 确认 docling-serve 进程存活、端口可达、URL 无尾部路径 |
| 解析报 `PARSER_TIMEOUT` | 大文档超过 600s：调大 `DOCLING_MAX_WAIT_SECONDS`、上 GPU 镜像或 RQ 扩容 |
| 首次解析特别慢 | 模型懒下载；可先用小文件预热，或在镜像/卷中预置模型缓存 |

## 解析文档引擎选择docling时

选择 DOC_PARSER_ENGINE=docling 后，解析链是 Lightweight → Csv → Docling（MinerU 完全不注册），各格式归属如下：

┌─────────────────────────────────┬───────────────────────────┬─────────────────────────┐
│              格式               │          解析器           │          条件           │
├─────────────────────────────────┼───────────────────────────┼─────────────────────────┤
│ .md / .markdown / .txt          │ LightweightParser（本地） │ 恒可用                  │
├─────────────────────────────────┼───────────────────────────┼─────────────────────────┤
│ .csv                            │ CsvParser（本地）         │ 恒可用                  │
├─────────────────────────────────┼───────────────────────────┼─────────────────────────┤
│ .pdf                            │ Docling                   │ 需配置 DOCLING_BASE_URL │
├─────────────────────────────────┼───────────────────────────┼─────────────────────────┤
│ .docx（Word）                   │ Docling                   │ 同上                    │
├─────────────────────────────────┼───────────────────────────┼─────────────────────────┤
│ .pptx（PPT）                    │ Docling                   │ 同上                    │
├─────────────────────────────────┼───────────────────────────┼─────────────────────────┤
│ .xlsx（Excel）                  │ Docling                   │ 同上                    │
├─────────────────────────────────┼───────────────────────────┼─────────────────────────┤
│ .png / .jpg / .jpeg（图片 OCR） │ Docling                   │ 同上                    │
├─────────────────────────────────┼───────────────────────────┼─────────────────────────┤
│ .html / .htm                    │ Docling（独占格式）       │ 同上                    │
└─────────────────────────────────┴───────────────────────────┴─────────────────────────┘

也就是说 Docling 引擎下共支持 13 种扩展名：4 种本地轻量格式 + 9 种走 docling-serve 的重型格式。与 auto 模式的区别在于 PDF/Office/图片这七种共有格式也全部由 Docling 解析（auto 下这些归 MinerU），Document.parser_name 会记录为 DOCLING。

两个提醒：

1. 你本地 .env 目前是 DOC_PARSER_ENGINE=docling 但 DOCLING_BASE_URL 还是空的——这种状态下 Docling 的 9 种格式全部不可用（上传直接 415），实际只能传 md/txt/csv。要生效需要先部署 docling-serve 并填上地址（如 http://127.0.0.1:5001），且 API 和 worker 进程都要重启。
2. 旧版 office 格式（.doc/.ppt/.xls）两个引擎都不支持（仅 OOXML）。另外 Docling 库本身还能解析 AsciiDoc、EPUB 甚至音频，但 lingxi 目前只把上表 9 种扩展名路由给它——将来要放开新格式，只需在 DoclingParser.extensions 元数据里加扩展名即可（上传白名单会自动跟随）。

## 参考资料

- [docling-serve GitHub](https://github.com/docling-project/docling-serve)
- [docling-serve 使用文档](https://github.com/docling-project/docling-serve/blob/main/docs/usage.md)
- [docling-serve 部署文档](https://github.com/docling-project/docling-serve/blob/main/docs/deployment.md)
- [Docling REST API 参考](https://docling-project.github.io/docling/usage/api_server/rest_api/)
- [Docling 支持格式](https://docling-project.github.io/docling/usage/supported_formats/)
