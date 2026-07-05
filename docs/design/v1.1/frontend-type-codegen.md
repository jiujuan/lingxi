# 前后端类型 Codegen（OpenAPI → TypeScript）

> 目标：前端类型从后端 OpenAPI 契约生成，杜绝手写 `types.ts` 与后端 schema 漂移。
> 相关：`server/scripts/export_openapi.py`、`web/admin/openapi.json`、`web/admin/src/api/schema.d.ts`、`web/admin/src/api/schema-helpers.ts`。

## 生成流程

两步（后端导出契约 → 前端生成类型）：

```bash
# 1. 从 FastAPI 导出 OpenAPI 契约到 web/admin/openapi.json
python -m server.scripts.export_openapi

# 2. 用 openapi-typescript 重新生成 TS 类型
npm --prefix web/admin run gen:api      # 产出 web/admin/src/api/schema.d.ts
```

`schema.d.ts` 由工具自动生成，**不要手改**。`openapi.json` 作为契约快照提交入库，使前端无需运行后端即可重新生成类型，也便于在 PR 里 review 契约变更。

## 使用方式

`schema-helpers.ts` 暴露生成类型的便捷别名，优先用它替代手写接口：

```ts
import type { TokenResponse, Schemas } from '../api/schema-helpers';

// 具名别名
type LoginResponse = TokenResponse;

// 或按需取任意 schema 组件
type ApiKey = Schemas['ApiKeyResponse'];
```

各 feature 的 `api/*.ts` 与 `types.ts` 应逐步迁移到 `Schemas[...]`；已示范 `LoginPage` 使用生成的 `TokenResponse`。

## CI / 防漂移

在 CI 中加入"契约漂移检查"：重新生成后若有 diff 说明后端改了 schema 但未同步前端类型，应判失败。

```bash
python -m server.scripts.export_openapi
npm --prefix web/admin run gen:api
git diff --exit-code web/admin/openapi.json web/admin/src/api/schema.d.ts \
  || { echo "OpenAPI 契约已变更，请提交重新生成的类型"; exit 1; }
```

> 说明：运行期校验（zod）为可选增强，暂未引入；当前在数据入口以生成类型做编译期约束。后端字段改名/结构变更会在 `tsc`/构建期暴露，而非运行期取到 `undefined` 才发现。
