# 服务器 Docker Compose 部署

适用于 Linux 服务器或安装了 Docker Desktop 的服务器环境，使用 `deploy/docker-compose.yml` 启动 PostgreSQL、Redis、API、Worker 和 Web Admin。

## 1. 前置依赖

- Docker Engine 或 Docker Desktop
- Docker Compose v2
- Git

确认命令：

```bash
docker --version
docker compose version
git --version
```

## 2. 获取代码

```bash
git clone <your-repo-url> lingxi
cd lingxi
```

如果已经有代码：

```bash
cd lingxi
git pull
```

## 3. 准备环境变量

复制模板：

```bash
cp .env.example .env
```

服务器环境建议至少修改：

```env
APP_ENV=production

POSTGRES_DB=lingxi
POSTGRES_USER=postgres
POSTGRES_PASSWORD=change-this-postgres-password

REDIS_PASSWORD=change-this-redis-password

JWT_SECRET_KEY=change-this-long-random-secret
SECRET_ENCRYPTION_KEY=change-this-independent-secret

SEED_ADMIN_EMAIL=admin@example.com
SEED_ADMIN_PASSWORD=change-this-admin-password
SEED_EMPLOYEE_EMAIL=employee@example.com
SEED_EMPLOYEE_PASSWORD=change-this-employee-password

API_PORT=8000
WEB_ADMIN_PORT=5173
VITE_API_BASE_URL=http://your-server-host:8000
```

如果前端通过域名访问后端，`VITE_API_BASE_URL` 应改为真实 API 地址，例如：

```env
VITE_API_BASE_URL=https://api.example.com
```

## 4. 启动服务

在项目根目录执行：

```bash
docker compose -f deploy/docker-compose.yml up --build -d
```

Compose 会启动：

- `postgres`
- `redis`
- `api`
- `worker`
- `web-admin`

`api` 容器启动时会执行：

```bash
alembic upgrade head
uvicorn server.app.main:app --host 0.0.0.0 --port 8000
```

## 5. 初始化账号和权限数据

首次部署后执行一次：

```bash
docker compose -f deploy/docker-compose.yml exec api python -c "from server.app.db.session import SessionLocal; from server.app.services.seed_service import seed_identity_data; session=SessionLocal(); seed_identity_data(session); session.close()"
```

默认账号由 `.env` 的 `SEED_*` 配置决定。

## 6. 检查服务状态

查看容器状态：

```bash
docker compose -f deploy/docker-compose.yml ps
```

查看 API 健康：

```bash
curl http://127.0.0.1:8000/health
```

查看日志：

```bash
docker compose -f deploy/docker-compose.yml logs -f api
docker compose -f deploy/docker-compose.yml logs -f worker
docker compose -f deploy/docker-compose.yml logs -f web-admin
```

访问前端：

```text
http://your-server-host:5173
```

## 7. 前后端启动命令说明

Docker Compose 中实际启动命令：

| 服务 | 启动命令 |
| --- | --- |
| API | `alembic upgrade head && uvicorn server.app.main:app --host 0.0.0.0 --port 8000` |
| Worker | `celery -A server.app.tasks.celery_app.celery_app worker -Q "$CELERY_QUEUE_NAMES" --loglevel="$CELERY_LOG_LEVEL"` |
| Web Admin | `npm run dev -- --host 0.0.0.0` |

如果需要手动进入容器排查：

```bash
docker compose -f deploy/docker-compose.yml exec api bash
docker compose -f deploy/docker-compose.yml exec worker bash
docker compose -f deploy/docker-compose.yml exec web-admin sh
```

## 8. 更新部署

拉取新代码并重建：

```bash
git pull
docker compose -f deploy/docker-compose.yml up --build -d
```

迁移由 `api` 容器启动命令自动执行。更新后建议检查：

```bash
docker compose -f deploy/docker-compose.yml ps
curl http://127.0.0.1:8000/health
```

## 9. 停止和清理

停止服务但保留数据卷：

```bash
docker compose -f deploy/docker-compose.yml down
```

停止并删除数据库、对象存储等 volume 数据：

```bash
docker compose -f deploy/docker-compose.yml down -v
```

生产环境不要随意执行 `down -v`。

## 10. 数据持久化

Compose 使用两个 volume：

| Volume | 用途 |
| --- | --- |
| `postgres_data` | PostgreSQL 数据 |
| `object_storage` | 本地对象存储，保存上传原文件和解析产物 |

API 和 Worker 共享 `object_storage`，否则 Worker 无法读取 API 上传的文件。

## 11. 反向代理建议

生产环境建议在外层使用 Nginx、Caddy 或云负载均衡：

- `/` 转发到 Web Admin `5173`
- `/api/` 转发到 API `8000`
- `/v1/` 转发到 API `8000`
- SSE 路由关闭代理缓冲
- 上传大小限制与 `UPLOAD_MAX_FILE_SIZE_BYTES` 保持一致
- 启用 HTTPS

Nginx SSE 关键配置示例：

```nginx
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 3600s;
```

## 12. 上线前检查清单

- [ ] `.env` 中已修改数据库密码、Redis 密码、JWT Secret、Secret 加密密钥。
- [ ] 已执行 seed 初始化账号。
- [ ] `docker compose ps` 中所有服务为 healthy 或 running。
- [ ] `curl http://127.0.0.1:8000/health` 返回 `status=ok`。
- [ ] 前端可访问并能登录。
- [ ] Worker 日志中没有持续报错。
- [ ] 上传文档后任务能从 `PARSING` 进入后续阶段。
- [ ] 服务器防火墙只开放必要端口。

