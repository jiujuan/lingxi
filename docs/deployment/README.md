# Lingxi 部署文档

本目录用于记录 Lingxi V1.1 的部署和启动方式。

## 文档列表

- [本地非 Docker 部署](./local-no-docker.md)
- [服务器 Docker Compose 部署](./server-docker-compose.md)
- [本地部署 MinerU 解析服务](./mineru-local.md)（可选，启用 PDF/Office/图片摄取）
- [本地部署 Docling 解析服务](./docling-local.md)（可选，第二解析引擎，独占 HTML 摄取）

## 当前服务组成

| 服务 | 技术 | 默认端口 | 说明 |
| --- | --- | --- | --- |
| API Server | FastAPI + Uvicorn | `8000` | 后端 REST API、SSE、OpenAI 兼容 API |
| Worker | Celery | 无 HTTP 端口 | 文档解析、QA 拆分、Embedding 异步任务 |
| Web Admin | React + Vite | `5173` | 管理后台和 Chat UI |
| PostgreSQL | PostgreSQL + pgvector | `5432` | 业务数据、全文检索、向量、日志 |
| Redis | Redis | `6379` | Celery broker/result backend |
| MinerU（可选） | mineru-api / mineru-router | `8888` | 重型解析引擎（PDF/Office/图片）；未部署时这些格式在上传入口被拒绝 |
| Docling（可选） | docling-serve | `5001` | 第二重型解析引擎（PDF/Office/图片/HTML）；经 `DOC_PARSER_ENGINE` 选择 |

## 默认测试账号

初始化 seed 数据后可使用：

| 用户 | 邮箱 | 密码 |
| --- | --- | --- |
| 系统管理员 | `admin@example.com` | `Admin123!` |
| 员工 | `employee@example.com` | `Employee123!` |

生产环境必须在 `.env` 中修改 `JWT_SECRET_KEY`、`SECRET_ENCRYPTION_KEY`、数据库密码和默认账号密码。

