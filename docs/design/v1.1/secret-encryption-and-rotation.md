# 密钥加密与轮换（Secret Encryption & Key Rotation）

> 适用范围：Provider API Key 的信封加密（`ModelProvider.encrypted_api_key`）。
> 相关代码：`server/app/core/secrets.py`、`server/scripts/reencrypt_secrets.py`。

## 加密方案

- 算法：**AES-256-GCM**（`cryptography` 库的 AEAD），取代早期自研的 SHA256 流密码。
- 信封格式：`enc:v2:<b64url nonce>:<b64url ciphertext+tag>`。
- 密钥派生：`AES key = SHA256(SECRET_ENCRYPTION_KEY)`（32 字节）。
- nonce：每次加密随机生成 12 字节，绝不复用。
- 兼容旧数据：`decrypt_secret` 仍能解密历史 `enc:v1:` 记录（读旧），但**新写入一律 `enc:v2`**。

`SECRET_ENCRYPTION_KEY` 与 `JWT_SECRET_KEY` 相互独立（见 `validate_secret_config`）；生产环境启动即校验两者已设置、≥32 字符且互不相同。

## 格式迁移（enc:v1 → enc:v2）

对历史库执行一次（同一把密钥，仅升级格式）：

```bash
python -m server.scripts.reencrypt_secrets
```

脚本幂等：能用当前密钥解密的记录会被重写为 `enc:v2`。

## 密钥轮换（Key Rotation）

1. 生成新密钥：`python -c "import secrets; print(secrets.token_urlsafe(48))"`。
2. 部署新的 `SECRET_ENCRYPTION_KEY`，同时**保留旧值**备用。
3. 用旧密钥解密、新密钥重加密：

```bash
OLD_SECRET_ENCRYPTION_KEY=<旧值> SECRET_ENCRYPTION_KEY=<新值> \
    python -m server.scripts.reencrypt_secrets
```

4. 脚本报告成功后，移除 `OLD_SECRET_ENCRYPTION_KEY`。

> 说明：API Key 的存储哈希（`api_key_security.hash_api_key`，HMAC-SHA256）也用 `SECRET_ENCRYPTION_KEY` 作为 HMAC 密钥。它是**单向哈希**，轮换密钥会使已签发的 API Key 校验失效——轮换后需重新签发 API Key（或单独为其保留一把稳定的 HMAC 密钥，属后续增强项）。

## 数据库迁移策略

- `0001_identity_documents_core` 为 **baseline**（建表 + pgvector/tsvector 索引）。
- 后续变更一律为**增量 revision**（如 `0002_user_token_version` 的 `add_column`）。
- `env.py` 已开启 `compare_type` / `compare_server_default`，支持 `alembic revision --autogenerate`。
- 生成新迁移：`alembic revision --autogenerate -m "描述"`，人工复核后 `alembic upgrade head`。
