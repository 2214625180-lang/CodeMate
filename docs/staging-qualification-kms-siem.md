# Staging Release Qualification、KMS 与 SIEM

这一阶段提供真正会阻止发布的 staging qualification。只有真实 HTTPS staging、AWS KMS、SIEM HTTP 接收端、启用 Object Lock 的 S3 bucket、MCP 压测和三项故障演练全部通过，报告才会给出 `qualified`；本地或模拟环境永远只能得到 `hold`。

## 1. Staging 部署

```bash
cp deploy/staging/.env.staging.example deploy/staging/.env.staging
# 从 Secret Manager/IAM role 注入真实值，不要提交该文件。
docker compose \
  --env-file deploy/staging/.env.staging \
  -f deploy/staging/docker-compose.yml \
  up -d --build
```

Staging Compose 不挂载源代码，PostgreSQL 与 Redis 使用持久卷，Backend readiness 会验证数据库、Redis、Alembic head、安全审计 outbox 和 RQ Worker 心跳。`RQ_WORKER_READINESS_REQUIRED=true` 在 staging/production 为强制项；所有 Worker 消失并超过心跳 TTL 后，readiness 必须失败。`MCP_REGISTRY_ALLOWED_HOSTS` 也必须显式列出 MCP、OAuth 和回调主机，作为 DNS/SSRF 防护的应用层边界；`MCP_ALLOWED_REPO_IDS` 必须显式限定只读 MCP Server 可见的仓库，空值不允许进入 staging/production。

## 2. KMS 信封加密与迁移

Credential Broker 使用每条凭据独立的 AES-256 data key。AWS KMS `GenerateDataKey` 返回明文 data key 与加密 data key；CodeMate 只把加密 data key、nonce、ciphertext、KMS Key ID 和算法版本写入数据库。解密使用相同 Encryption Context，数据库泄露本身不足以恢复凭据。

运行身份最小权限：

- `kms:GenerateDataKey`；
- `kms:Decrypt`；
- `kms:DescribeKey`（运维验证）。

从旧 application master key 迁移：

1. 备份数据库并部署支持 KMS envelope 的版本；
2. 设置 `MCP_REGISTRY_KMS_PROVIDER=aws`、`MCP_REGISTRY_KMS_KEY_ID`，临时保留旧 `MCP_REGISTRY_MASTER_KEY`；
3. 执行 `python -m app.core.kms` 验证 KMS round-trip；
4. 调用管理员接口 `POST /mcp-registry/credentials/rewrap`；
5. 确认 Registry API 中所有 credential 的 `encryption_provider` 都是 `aws`；
6. 清空旧 master key，再次验证 Server credential 解密与 MCP 调用。

KMS key rotation 不需要解密数据库中的业务密文；AWS KMS ciphertext blob 会记录实际 key version。需要切换不同 CMK 时，再执行一次 rewrap。

## 3. Durable SIEM + 不可变存储

每个安全事件先写本地 emergency JSONL，再按配置为 `http` 与 `s3` 各创建一条 PostgreSQL outbox delivery。Worker 使用租约认领、指数退避和 dead-letter 状态，崩溃后可继续投递。

Staging/production 强制 `SECURITY_AUDIT_FAIL_CLOSED=true`：中间件会在进入 handler 前先持久化 request intent，无法写入 durable outbox 时不会执行管理操作；handler 完成后再写入包含主体和结果的 completion event。

Next.js proxy/OAuth/session 事件通过仅容器内可达的 `/security-audit/events` 和独立 `SECURITY_AUDIT_INGEST_TOKEN` 汇入同一 outbox；该 token 不进入浏览器 bundle。

SIEM HTTP 请求包含：

- `Idempotency-Key`：安全事件 UUID；
- `X-CodeMate-Event-SHA256`：canonical JSON SHA-256；
- `X-CodeMate-Timestamp`；
- `X-CodeMate-Signature: sha256=<HMAC>`，签名内容为 `<timestamp>.<payload_sha256>`。

SIEM 必须按 Idempotency Key 去重、验证 HMAC 和时间窗口，并返回 2xx。不要允许 HTTP redirect 携带签名。

S3 sink 使用独立事件对象、SHA-256 checksum、Version ID 和 `COMPLIANCE` Object Lock。Bucket 必须在创建时启用 Object Lock；运行身份只需要目标 prefix 的 `s3:PutObject`。建议另一个审计账号拥有读取和 retention 管理权限。

已成功投递的本地 outbox receipt 默认保留 90 天后清理；pending、retry 和 dead-letter 不会被 retention 删除，长期权威事件仍由 SIEM 与 Object-Locked S3 保存。

修复外部接收端后，可在 Operations Dashboard 使用 `Requeue dead letters`，或执行 `python -m app.services.security_audit_delivery_service requeue`；重放仍使用原事件 UUID，接收端必须幂等。

手动验证：

```bash
docker compose --env-file deploy/staging/.env.staging \
  -f deploy/staging/docker-compose.yml exec -T backend \
  python -m app.services.security_audit_delivery_service verify
```

该命令会执行 KMS round-trip，生成 synthetic audit probe，并要求 SIEM 与 S3 receipt 都进入 `delivered`。

## 4. 执行 Qualification

在 staging 主机或拥有 staging Docker context 的 self-hosted runner 上：

```bash
export STAGING_BASE_URL=https://api.staging.example.com
export MCP_CLIENT_API_TOKEN='...'
export MCP_TENANT_ID='...'
export MCP_TENANT_TOKEN='...'

python scripts/run_staging_qualification.py \
  --execute \
  --compose-file deploy/staging/docker-compose.yml \
  --env-file deploy/staging/.env.staging \
  --server tracker \
  --tool search_issue \
  --requests 1000 \
  --concurrency 50
```

Qualification 顺序：

1. Compose、MCP container policy 与 runtime security config；
2. readiness、Alembic head；
3. KMS + SIEM + S3 synthetic probe，以及 Sandbox Broker/Gateway runtime compliance 与负向 egress canary；
4. MCP load gate（吞吐、成功率、P50/P95/P99、quota 拒绝原因）；
5. Redis stop/start、PostgreSQL stop/start、Worker kill/start；每项都必须同时观察到容器停止和 readiness outage；
6. 最终 readiness 与 Compose 状态。

任何 preflight 失败都会跳过压测和故障注入。`--skip-faults`、`--allow-local-rehearsal` 或任意 Gate 失败都会输出 `decision: hold` 并返回非零状态。

证据目录包含 `qualification.json`、`qualification.md`、load/fault JSON、每个命令的 stdout/stderr 和 `manifest.sha256`。GitHub Actions 手动工作流使用受保护的 `staging` Environment 与 self-hosted runner 执行相同流程。

## 5. 发布判定

发布前必须同时满足：

- `qualification.json` 为 `qualified`；
- `manifest.sha256` 校验通过；
- 没有 SIEM dead-letter 或过期 outbox；
- 所有 credential 已迁移为 AWS KMS envelope；
- 压测阈值与故障恢复时间满足当前 SLO；
- 证据由非执行者复核并记录审批。
