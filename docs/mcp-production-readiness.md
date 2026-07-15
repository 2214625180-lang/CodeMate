# MCP Production Readiness & Evidence Pack

这一阶段把 CodeMate 从功能完整 MVP 推进到“可迁移、可验证、可故障演练、可提交证据”的工程状态。

## 发布门禁

GitHub Actions 工作流 `.github/workflows/production-readiness.yml` 包含：

1. Backend Ruff、compileall 和完整 Pytest；
2. Python 依赖安全审计；
3. Frontend ESLint、TypeScript、production build 和 npm audit；
4. 真实 PostgreSQL、Redis、Streamable HTTP MCP Server、OAuth Provider E2E；
5. Alembic upgrade、drift check、downgrade 和再次 upgrade；
6. Backend、Worker、Migration 和 Frontend 容器构建。

## Alembic 数据库迁移

正常启动不再调用 `create_all` 或运行临时列升级。Backend 启动和 Compose `migrate` service 都执行 Alembic upgrade。

```bash
cd backend
alembic -c alembic.ini upgrade head
python -m app.core.migrations check
```

已经存在但没有 `alembic_version` 的旧数据库会被拒绝，避免把不完整 Schema 静默标记为最新版本。迁移前先备份，然后显式执行：

```bash
cd backend
python -m app.core.migrations adopt-legacy --yes
```

Legacy adoption 只用于一次性接管：它补齐历史 bridge 字段、验证所有 ORM table/column 存在，再 stamp 当前 head。之后所有变化都必须通过新 revision。

破坏性的 downgrade 需要显式确认：

```bash
python -m app.core.migrations downgrade-base --yes
```

## Quota 双存储对账和保留

Redis 提供实时原子限制，PostgreSQL 保存 Durable Quota Ledger。后台任务按 `MCP_QUOTA_RECONCILIATION_INTERVAL_SECONDS` 对比当前分钟、当日调用、成本和并发租约。

对账使用 Tenant lock；实时 Lua limiter 检测到 lock 时返回 `quota_reconciling`，避免 repair 覆盖同时发生的新计数。修复结果写入 `mcp_quota_reconciliations`，形成长期证据。

管理 API：

- `POST /mcp-quotas/tenants/{id}/reconcile`，`repair=false` 只审计，`true` 修复；
- `GET /mcp-quotas/tenants/{id}/reconciliations`；
- `POST /mcp-quotas/tenants/{id}/retention`。

默认保留 90 天，最短 30 天。Retention 只删除租约已释放或过期的历史事件，并先支持 dry-run。

## 一键真实基础设施证据

需要 Docker、Backend virtualenv 和空闲的本机端口 5432、6379、8765、8766：

```bash
python scripts/run_mcp_production_evidence.py
```

该命令会：

1. 启动 PostgreSQL 和 Redis；
2. 执行 Alembic upgrade；
3. 启动真实 Streamable HTTP MCP fixture 和 OAuth fixture；
4. 验证 MCP 调用、Redis quota、幂等免重复计费、超限拒绝、Redis drift repair 和 OAuth PKCE token exchange；
5. 输出 JUnit 与 JSON 到 `artifacts/production-evidence/`；
6. 默认停止本次启动的基础设施，`--keep-services` 可保留。

旧数据库必须先按上文完成 legacy adoption。一键证据命令不会自动 stamp 旧库。

## 压测

```bash
python scripts/mcp_load_test.py \
  --api-token "$MCP_CLIENT_API_TOKEN" \
  --tenant-id "$TENANT_ID" \
  --tenant-token "$TENANT_TOKEN" \
  --server evidence \
  --tool echo \
  --requests 1000 \
  --concurrency 50 \
  --max-p95-ms 2000 \
  --min-success-rate 0.99
```

输出包括吞吐、成功率、HTTP 状态、quota 拒绝原因和 P50/P95/P99。命令会根据阈值返回非零状态，可直接作为发布 Gate。

`--idempotency-reuse 5` 可以让每五个请求共享一个 Idempotency Key，验证计费去重行为。注意：远端 Tool 是否真正去重仍取决于其 idempotency contract。

## 故障演练

故障脚本默认拒绝修改环境，必须显式传 `--execute`：

```bash
python scripts/mcp_fault_injection.py redis-restart --execute
python scripts/mcp_fault_injection.py postgres-restart --execute
python scripts/mcp_fault_injection.py worker-crash --execute
```

每次演练记录操作前、故障期间、恢复后的 API Health 和 Compose 状态，并确保被 kill 的 Worker 在 `finally` 中恢复。证据输出到 `artifacts/production-evidence/fault-injection.json`。

不要对共享生产环境直接运行该脚本；应使用隔离的 staging namespace 和经过审批的变更窗口。

## 证据清单

- Unit/API 测试结果；
- Alembic upgrade/downgrade/drift check；
- Real-infrastructure JUnit；
- Redis reconciliation history；
- Load test JSON；
- Fault injection JSON；
- Dashboard 截图和 Prometheus 快照；
- 当前版本威胁模型与 ADR。

报告模板位于 [production-evidence-template.md](production-evidence-template.md)。

真实 staging 的 KMS、SIEM、不变对象存储、压测与故障演练流程见 [staging-qualification-kms-siem.md](staging-qualification-kms-siem.md)。
