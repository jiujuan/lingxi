# T01 V1.1 运行时与工程骨架

## 任务状态

- 状态：IN_PROGRESS
- 完成任务进度：80%
- 优先级：P0
- 预计范围：中

## Task 目标

建立最小可运行的后端、前端、Worker、数据库、Redis 和 Docker Compose 工程骨架，让后续任务可以在稳定目录和运行时上增量开发。

## 实现功能

- FastAPI 应用入口、健康检查和 `/api/v1` 路由注册。
- Celery 应用和 `parse`、`qa`、`embedding`、`maintenance` 队列声明。
- SQLAlchemy session、Alembic 初始化和 PostgreSQL 连接配置。
- Redis 连接配置。
- request_id 基础中间件和结构化日志。
- React + TypeScript + Vite 管理端骨架。
- Docker Compose 启动 PostgreSQL、Redis、API、Worker、前端开发服务。

## 修改或增加文件

- `server/app/main.py`
- `server/app/api/v1/__init__.py`
- `server/app/core/config.py`
- `server/app/core/logging.py`
- `server/app/core/ids.py`
- `server/app/db/session.py`
- `server/app/db/base.py`
- `server/app/tasks/celery_app.py`
- `web/admin/src/app/App.tsx`
- `web/admin/src/routes/index.tsx`
- `web/admin/src/api/client.ts`
- `deploy/docker-compose.yml`

## 不修改范围

- 不实现业务表和业务 API。
- 不实现登录、上传、Chat、模型配置。
- 不引入 Widget、IM、工单、计费模块。

## 涉及其它 Task

- 被 T02-T17 依赖。
- T03 使用本任务的数据库和迁移入口。
- T05-T08 使用本任务的 Celery 队列。

## 测试策略

- 后端健康检查接口测试。
- Celery app import 和队列注册测试。
- 数据库连接 smoke test。
- 前端 `npm run build` 或等价构建测试。
- Docker Compose 启动 smoke test。

## 长任务链路验收策略

本地启动 Docker Compose，确认 API health check、Worker 启动日志、PostgreSQL 连接和前端页面均可访问。

## 验收功能清单

- [x] API 服务可启动。
- [x] `/health` 或等价健康检查返回成功。
- [x] Celery app 可加载并注册 `parse`、`qa`、`embedding`、`maintenance` 队列。
- [ ] PostgreSQL 和 Redis 容器连接可用。
- [x] Alembic 目录初始化完成，baseline migration 可执行。
- [x] 前端 Vite 工程可构建。
- [ ] Docker Compose 可启动核心服务。

## 验收结果

- 已实现 FastAPI 入口、request_id 中间件、结构化日志入口、SQLAlchemy session、Alembic baseline、Celery app、React/Vite 管理端骨架和 Docker Compose 配置。
- 验证通过：`python -m pytest server\tests`，7 passed。
- 验证通过：`$env:DATABASE_URL='sqlite+pysqlite:///:memory:'; python -m alembic upgrade head`。
- 验证通过：`npm --prefix web\admin run build`。
- 未完成实机验收：当前环境未安装 Docker CLI，无法执行 `docker compose config/up`，PostgreSQL 和 Redis 容器连接待有 Docker 环境后验证。

## 完成任务进度

80%
