# 本地非 Docker 部署

适用于开发机直接运行后端、Worker 和前端，不使用 Docker。

## 1. 前置依赖

- Python 3.13
- Node.js 24 或兼容版本
- PostgreSQL 16，并安装 pgvector 扩展
- Redis 7
- PowerShell

确认命令：

```powershell
python --version
node --version
npm --version
psql --version
redis-server --version
```

## 2. 准备 PostgreSQL

创建数据库和 pgvector 扩展：

```powershell
psql -U postgres
```

进入 psql 后执行：

```sql
CREATE DATABASE lingxi;
\c lingxi
CREATE EXTENSION IF NOT EXISTS vector;
```

如果 PostgreSQL 账号不是 `postgres`，后续在 `.env` 中同步修改 `POSTGRES_USER`、`POSTGRES_PASSWORD`。

## 3. 准备 Redis

本地开发可以直接启动：

```powershell
redis-server
```

如果 Redis 设置了密码，在 `.env` 中填写：

```env
REDIS_PASSWORD=your-redis-password
```

## 4. 准备环境变量

复制模板：

```powershell
Copy-Item .env.example .env
```

至少确认这些配置：

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=lingxi
POSTGRES_USER=postgres
POSTGRES_PASSWORD=

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0
REDIS_CELERY_BROKER_DB=1
REDIS_CELERY_RESULT_DB=2

OBJECT_STORAGE_BACKEND=local
LOCAL_STORAGE_ROOT=.data/object-storage

JWT_SECRET_KEY=change-me-in-local-dev
SECRET_ENCRYPTION_KEY=

VITE_API_BASE_URL=http://localhost:8000
```

`DATABASE_URL`、`REDIS_URL`、`CELERY_BROKER_URL`、`CELERY_RESULT_BACKEND` 可以留空，程序会根据拆分字段自动拼接。

## 5. 安装后端依赖

在项目根目录执行：

```powershell
cd lingxi
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 6. 数据库迁移

```powershell
alembic upgrade head
```

## 7. 初始化登录账号和权限数据

当前应用不会在启动时自动初始化账号。首次部署后执行一次：

```powershell
python -c "from server.app.db.session import SessionLocal; from server.app.services.seed_service import seed_identity_data; session=SessionLocal(); seed_identity_data(session); session.close()"
```

执行后默认账号来自 `.env`：

```env
SEED_ADMIN_EMAIL=admin@example.com
SEED_ADMIN_PASSWORD=Admin123!
SEED_EMPLOYEE_EMAIL=employee@example.com
SEED_EMPLOYEE_PASSWORD=Employee123!
```

## 8. 启动后端 API

新开一个 PowerShell 窗口：

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn server.app.main:app --host 0.0.0.0 --port 8000 --reload
```

健康检查：

```powershell
Invoke-RestMethod http://localhost:8000/health
```

## 9. 启动 Celery Worker

新开一个 PowerShell 窗口：

```powershell
.\.venv\Scripts\Activate.ps1
celery -A server.app.tasks.celery_app.celery_app worker -Q parse,qa,embedding,maintenance --loglevel=INFO
```

如果只想启动某些队列：

```powershell
celery -A server.app.tasks.celery_app.celery_app worker -Q parse,qa --loglevel=INFO
```

## 10. 启动前端 Web Admin

新开一个 PowerShell 窗口：

```powershell
cd web\admin
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

访问：

```text
http://localhost:5173
```

## 11. 常用开发命令

后端测试：

```powershell
python -m pytest server\tests
```

前端构建：

```powershell
cd web\admin
npm run build
```

性能基线：

```powershell
python scripts\perf\retrieval_baseline.py 30
python scripts\perf\chat_first_token_baseline.py 20
```

## 12. 启动顺序

推荐顺序：

```text
PostgreSQL -> Redis -> alembic upgrade head -> seed 数据 -> API -> Worker -> Web Admin
```

## 13. 常见问题

### 登录失败

确认已经执行 seed：

```powershell
python -c "from server.app.db.session import SessionLocal; from server.app.services.seed_service import seed_identity_data; session=SessionLocal(); print(seed_identity_data(session)['tenant'].name); session.close()"
```

### 文档上传后任务不继续

确认 Worker 已启动，并且队列包含：

```text
parse,qa,embedding,maintenance
```

### API 无法连接数据库

确认 `.env` 中 `POSTGRES_*` 与本机 PostgreSQL 一致；如果设置了 `DATABASE_URL`，它会优先于拆分字段。

### 前端无法访问 API

确认：

```env
VITE_API_BASE_URL=http://localhost:8000
```

修改后需要重新启动 `npm run dev`。

