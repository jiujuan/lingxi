# 本地部署 MinerU 解析服务

Lingxi 通过 HTTP 调用自部署的 `mineru-api` 完成 PDF / Word / PPT / Excel / 图片的文档解析（架构见 [07-document-parser-architecture.md](../design/v1.1/07-document-parser-architecture.md)）。**MinerU 是可选服务**：未配置 `MINERU_BASE_URL` 时系统正常运行，只是上述格式在上传入口直接被 415 拒绝，仅支持 md / txt / csv。

## 1. 部署方式选择

| 方式 | 适用场景 | 说明 |
| --- | --- | --- |
| A. pip 安装 + `mineru-api` | 开发机（Windows/macOS/Linux），无 GPU 也可跑 | CPU 用 pipeline 后端，速度慢但可用 |
| B. Docker（GPU） | Linux 服务器 + NVIDIA 显卡 | 官方镜像基于 vllm，解析快 3-15 倍 |
| C. `mineru-router` 多实例 | 生产多 GPU / 高并发 | 接口与 mineru-api 完全兼容 |

硬件参考：CPU 模式建议 8 核 32GB 内存（10 页纯文字 PDF 约 2-5 分钟）；GPU 模式要求 NVIDIA Turing 及以上（RTX 20/30/40、T4、A10 等）、显存 ≥ 8GB。

## 2. 方式 A：pip 安装（开发机推荐）

> ⚠️ MinerU 依赖 PyTorch 等重型包（数 GB），**必须使用独立的 Python 环境**（3.10–3.13），不要装进 Lingxi 的运行环境。

```powershell
# 独立虚拟环境（也可用 conda）
python -m venv D:\envs\mineru
D:\envs\mineru\Scripts\Activate.ps1

# 国内镜像安装（mineru[all] 自带 CPU 版 torch）
pip install --upgrade pip uv -i https://mirrors.aliyun.com/pypi/simple
uv pip install -U "mineru[all]" -i https://mirrors.aliyun.com/pypi/simple
```

有 NVIDIA 显卡（显存 ≥ 6GB）需要 GPU 加速时，另装 CUDA 版 torch（以 CUDA 12.8 为例）：

```powershell
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

### 2.1 下载模型（国内切 ModelScope 源）

MinerU 默认从 HuggingFace 拉模型，国内网络请切换到 ModelScope：

```powershell
$env:MINERU_MODEL_SOURCE = "modelscope"
mineru-models-download
```

下载完成后模型路径自动写入用户目录的 `mineru.json`。不预下载也可以——首次解析请求会触发自动下载（首个任务会明显变慢）。

### 2.2 启动 mineru-api

> ⚠️ 端口不要用 8000（与 Lingxi API 冲突），本文统一用 **8888**。

```powershell
# CPU 模式（无 GPU 的开发机）：必须切 pipeline 后端，默认的 vllm 后端仅支持 CUDA
$env:MINERU_MODEL_SOURCE = "modelscope"
$env:MINERU_DEVICE_MODE = "cpu"
mineru-api --host 127.0.0.1 --port 8888

# GPU 模式：直接启动即可，Linux/macOS 自动启用 CUDA/MPS 加速
mineru-api --host 0.0.0.0 --port 8888
```

验证：

```powershell
curl http://127.0.0.1:8888/health          # 期望 200
Start-Process http://127.0.0.1:8888/docs   # Swagger UI
```

## 3. 方式 B：Docker 部署（Linux + GPU）

官方镜像基于 `vllm/vllm-openai`（国内可用 `docker.m.daocloud.io` 前缀加速基础镜像），要求宿主机显卡驱动支持镜像对应的 CUDA 运行时：

```bash
docker run -d --name mineru-api \
  --gpus all --shm-size 32g --ipc=host \
  -p 8888:8000 \
  -e MINERU_MODEL_SOURCE=modelscope \
  -v mineru-models:/root/.cache \
  mineru:latest mineru-api --host 0.0.0.0 --port 8000
```

要点：

- 挂载模型缓存卷（`/root/.cache`），避免每次重建容器重新下载数 GB 模型；
- 官方 Docker 方案面向 GPU；纯 CPU 容器需自定义 Dockerfile 并使用 pipeline 后端，只建议测试用途，参考[官方 Docker 部署文档](https://opendatalab.github.io/MinerU/zh/quick_start/docker_deployment/)；
- macOS 不要用 Docker 跑 MinerU（容器内无法使用 MPS 加速）。

## 4. 对接 Lingxi

### 4.1 配置 `.env`

```env
MINERU_BASE_URL=http://127.0.0.1:8888
# 可选调优（默认值见 .env.example）
MINERU_TIMEOUT_MS=30000            # 单次 HTTP 调用超时（轮询类）
MINERU_MAX_WAIT_SECONDS=600        # 单文档解析整体截止时间
MINERU_POLL_INTERVAL_SECONDS=3.0
# 建议：PDF 常超过默认 10MB 上限，调大到 50MB
UPLOAD_MAX_FILE_SIZE_BYTES=52428800
```

**两处检查：**

1. 删掉存量 `.env` 中残留的 `UPLOAD_ALLOWED_EXTENSIONS=.md,...`——白名单按"env ∩ 解析器支持集"求交，残留旧值会把 PDF/Office 钉死在白名单之外；
2. `MINERU_BASE_URL` 必须让 **API 进程和 Celery worker 都读到**（上传门与解析链共用该配置），改完两者都要重启。

### 4.2 验证链路

```powershell
# 1) Lingxi 健康检查应显示 mineru: up（未配置时为 unconfigured）
curl http://localhost:8000/health

# 2) 包络冒烟（上线 checklist 必做）：mineru-api 各 3.x 版本响应结构有差异，
#    确认响应含 md_content / content_list（或 task_id），与客户端 _extract_result 匹配
curl -X POST http://127.0.0.1:8888/file_parse `
  -F "files=@sample.pdf" -F "return_md=true" -F "return_content_list=true"

# 3) 端到端：管理后台上传一个 PDF，观察导入任务走完 PARSING → QA_SPLITTING → EMBEDDING → COMPLETED
```

若步骤 2 的响应结构与预期不符（解析任务报 `PARSER_RESPONSE_INVALID`），调整点集中在 `server/app/integrations/parsers/mineru.py` 的 `_extract_result()`（设计上的唯一改动点）。

### 4.3 容量提示

一个解析任务最多占用 parse 队列 worker 槽位 `MINERU_MAX_WAIT_SECONDS`（默认 600s），失败后 Celery 层最多再重试 3 次。CPU 模式部署时建议调低 `MINERU_MAX_WAIT_SECONDS` 预期或控制并发上传量；parse 队列并发数按此评估。

## 5. 多实例 / 多 GPU（生产）

`mineru-api` 的任务状态保存在**进程内存**中（默认保留 24h，可用 `MINERU_API_TASK_RETENTION_SECONDS` 调整），多实例部署时任务提交与状态查询可能落到不同实例。生产多实例必须前置 `mineru-router` 做统一入口与任务路由（接口与 mineru-api 完全兼容，Lingxi 侧只需把 `MINERU_BASE_URL` 指向 router）：

```bash
mineru-router --host 0.0.0.0 --port 8888 \
  --upstream-url http://gpu-node-1:8888 \
  --upstream-url http://gpu-node-2:8888
```

## 6. 常见问题

| 现象 | 处理 |
| --- | --- |
| 纯 CPU 环境启动/解析报 vllm 相关错误 | vllm 后端仅支持 CUDA：设置 `MINERU_DEVICE_MODE=cpu` 并使用 pipeline 后端 |
| 模型下载慢/失败 | `MINERU_MODEL_SOURCE=modelscope` 切国内源，用 `mineru-models-download` 预下载 |
| GPU 显存不足 | 换 CPU 模式，或换 pipeline 后端（显存要求低于 vlm） |
| Lingxi `/health` 中 mineru: down | 确认 mineru-api 进程存活、端口可达、`MINERU_BASE_URL` 无拼写错误（不要带尾部路径） |
| 上传 PDF 仍返回 415 | `MINERU_BASE_URL` 未被 API 进程读到（未重启），或 `.env` 残留旧 `UPLOAD_ALLOWED_EXTENSIONS` |
| 解析任务报 `PARSER_TIMEOUT` | CPU 模式解析大文档超过 600s：调大 `MINERU_MAX_WAIT_SECONDS` 或上 GPU |

## 参考资料

- [MinerU 官方文档 · 快速入门](https://opendatalab.github.io/MinerU/zh/quick_start/)
- [MinerU 官方文档 · Docker 部署](https://opendatalab.github.io/MinerU/zh/quick_start/docker_deployment/)
- [MinerU 官方文档 · 模型源配置](https://opendatalab.github.io/MinerU/zh/usage/model_source/)
- [MinerU GitHub（中文 README）](https://github.com/opendatalab/MinerU/blob/master/README_zh-CN.md)
- [MinerU 更新日志](https://opendatalab.github.io/MinerU/zh/reference/changelog/)
