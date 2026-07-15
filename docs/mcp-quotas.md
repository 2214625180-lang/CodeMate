# Tenant-aware MCP Quotas, Rate Limiting and Budget Governance

这一阶段在 Tenant Authorization 之后增加 MCP 资源治理：CodeMate 可以按租户、仓库、主体、Server 和 Tool 限制调用速率、每日预算、Agent Run 预算和并发数。

Dashboard：

```text
http://localhost:3000/mcp-quotas
```

## 能力

- Tenant / Repository / Principal / Server / Tool 多层 scope；
- 每分钟调用数、每日调用数和每日 cost units；
- 每个 Agent Run 的调用数和最长运行时间；
- 并发租约与崩溃后的 TTL 自动释放；
- Agent、审批后执行、配置型上下文 Tool 和直连 MCP Client API 统一拦截；
- Durable quota event/charge ledger；
- Durable Execution 重试和客户端 Idempotency Key 不重复计费；
- Redis Lua 原子多策略预检查、计数和并发 ZSET；
- Redis 故障的 fail-closed / fail-open 行为；
- 委托用户身份单独 scope 和用量统计；
- 冻结、乐观锁更新、临时额度提升、预算重置和软禁用；
- `429 Too Many Requests`、`Retry-After` 和稳定的拒绝原因；
- 用量、成本、热点 Server/Tool/Principal、拒绝事件、预警和 Prometheus 指标。
- Redis/PostgreSQL 定时对账、租户级 repair lock、修复证据与历史数据保留。

## 启用

```env
MCP_QUOTA_ENABLED=true
MCP_QUOTA_BACKEND=redis
MCP_QUOTA_FAIL_CLOSED=true
MCP_QUOTA_REDIS_PREFIX=codemate:mcp:quota
MCP_QUOTA_CONCURRENCY_LEASE_SECONDS=180
MCP_QUOTA_MAX_POLICIES_PER_TENANT=64
MCP_QUOTA_DEFAULT_CALL_COST_UNITS=1
MCP_QUOTA_REJECTION_ALERT_THRESHOLD=5
MCP_QUOTA_RECONCILIATION_INTERVAL_SECONDS=300
MCP_QUOTA_RETENTION_DAYS=90
```

生产环境还必须启用：

```env
MCP_REGISTRY_ENABLED=true
MCP_TENANT_AUTHORIZATION_ENABLED=true
```

生产配置验证要求 quota backend 为 Redis 且 fail-closed。数据库模式只用于本地开发和确定性测试。

功能默认关闭。开启后，没有命中 Quota Policy 的已授权调用不会被限流或计费，因此建议首先为每个 Tenant 创建 `*/*` catch-all Policy，再添加更具体的 Repository、用户或 Tool Policy。所有匹配 Policy 会同时执行，任一 Policy 超限都会拒绝请求。

## Policy 示例

下面的策略限制一个 Tenant 内所有主体和 Tool：

```json
{
  "principal_type": "*",
  "principal_id": "*",
  "server_name": "*",
  "tool_name": "*",
  "rate_limit_per_minute": 60,
  "daily_call_limit": 10000,
  "daily_cost_limit": 20000,
  "concurrent_limit": 20,
  "run_call_limit": 20,
  "max_run_duration_seconds": 1800,
  "call_cost_units": 1,
  "warning_threshold": 0.8
}
```

更具体的策略可以设置：

```json
{
  "repo_id": "<repository UUID>",
  "principal_type": "user",
  "principal_id": "alice",
  "server_name": "tracker",
  "tool_name": "search_issue",
  "daily_call_limit": 200,
  "concurrent_limit": 2,
  "call_cost_units": 2.5
}
```

委托身份 Agent Run 的主体为 `user:<subject>`，因此可被 user Policy 或 Membership 对应的 role Policy 限制。普通 Agent 使用 `agent:codemate-agent`，直连 API 使用 `service:mcp-client`。

## 幂等计费和崩溃恢复

每次允许的逻辑调用创建唯一 `MCPQuotaEvent`，并为所有命中的 Policy 创建 `MCPQuotaCharge`：

- Agent Router 使用 Durable Execution 的 idempotency key；
- 配置型上下文 Tool 使用 Run、Server、Tool 和参数生成稳定 key；
- 直连 API 可传 `X-CodeMate-Idempotency-Key`；
- 相同 key 的重试重新获取并发租约，但不增加 minute/day/run/cost 计数；
- MCP 返回、明确失败或连接异常后释放并发租约；
- Worker 崩溃无法释放时，数据库和 Redis 租约会在 `MCP_QUOTA_CONCURRENCY_LEASE_SECONDS` 后过期。

Quota 拒绝发生在远程 MCP 网络调用前。它是已知的本地决策，不会被 Durable Execution 误标为 `unknown` 或进入人工对账。

## Redis 原子限制

Redis backend 使用单个 Lua Script 对所有匹配 Policy 完成两阶段操作：

1. 清理过期并发 lease；
2. 预检查 minute、day calls、day cost、run calls 和 concurrency；
3. 只有全部 Policy 通过才原子增加计数并写入 lease；
4. 用数据库中是否已存在 Quota Event 判断是否为幂等重试。

数据库仍保存长期审计账本和 Dashboard 数据，并通过 Policy row lock 提供第二层预算保护。Redis 不可用且 `MCP_QUOTA_FAIL_CLOSED=true` 时，调用在远程执行前返回 `mcp_quota_unavailable`。

## 直连 MCP Client API

开启 Tenant Authorization 和 Quota 后，直连调用需要全局 Token、Tenant Token 和 Tenant ID：

```bash
curl -X POST http://localhost:8000/mcp-client/servers/docs/call \
  -H "Authorization: Bearer ${MCP_CLIENT_API_TOKEN}" \
  -H "X-CodeMate-Tenant-ID: <tenant UUID>" \
  -H "X-CodeMate-Tenant-Token: <tenant token>" \
  -H "X-CodeMate-Idempotency-Key: request-123" \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"search","arguments":{"query":"MCP"}}'
```

超限响应：

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 30
```

```json
{
  "detail": {
    "code": "mcp_quota_exceeded",
    "reason": "rate_limit_per_minute",
    "policy_id": "<policy UUID>",
    "message": "MCP quota denied docs.search: rate_limit_per_minute"
  }
}
```

拒绝原因包括 `tenant_frozen`、`quota_reconciling`、`idempotency_in_progress`、`rate_limit_per_minute`、`daily_call_limit`、`daily_cost_limit`、`concurrent_limit`、`run_call_limit` 和 `run_duration_limit`。

## 管理 API

- `GET/POST /mcp-quotas/tenants/{tenant_id}/policies`；
- `PATCH /mcp-quotas/policies/{policy_id}`：带 `expected_version` 调整长期额度或冻结；
- `POST /mcp-quotas/policies/{policy_id}/temporary-adjustment`：60 秒到 7 天的临时额度；
- `POST /mcp-quotas/policies/{policy_id}/reset`：保留审计记录并重置当前计费窗口；
- `DELETE /mcp-quotas/policies/{policy_id}`：软禁用 Policy；
- `GET /mcp-quotas/tenants/{tenant_id}/overview`；
- `POST /mcp-quotas/tenants/{tenant_id}/reconcile`：审计或修复 Redis 漂移；
- `GET /mcp-quotas/tenants/{tenant_id}/reconciliations`：查看持久化对账证据；
- `POST /mcp-quotas/tenants/{tenant_id}/retention`：先 dry-run，再清理已结束的历史用量；
- `GET /mcp-quotas/tenants/{tenant_id}/metrics/prometheus`。

所有管理操作要求 Evaluation admin，并接入 signed browser identity、RBAC、乐观锁和安全审计。

## Prometheus

当前提供：

- `codemate_mcp_quota_calls`；
- `codemate_mcp_quota_cost_units`；
- `codemate_mcp_quota_rejections`；
- `codemate_mcp_quota_active_concurrency`；
- `codemate_mcp_quota_utilization`。

Dashboard 会在 Policy 使用率达到 `warning_threshold` 或窗口内拒绝数量达到 `MCP_QUOTA_REJECTION_ALERT_THRESHOLD` 时生成预警。
