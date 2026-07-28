# Durable MCP Execution Ledger

CodeMate 的所有动态 MCP Tool 调用都会先写入持久化 Execution Ledger，再获取有时限的执行租约。Ledger 将 Agent 的逻辑调用与远程网络请求分开，避免审批恢复、队列重复投递或 Worker 重启直接造成重复写入。

## 状态流转

```text
prepared → executing → succeeded
                   ↘ failed
                   ↘ unknown → confirm_succeeded / confirm_failed
                             ↘ retry（仅 metadata idempotency）

executing lease expired
  → metadata idempotency: prepared → same-key retry
  → no idempotency contract: unknown → human reconciliation
```

每次调用保存：

- 稳定的 SHA-256 `idempotency_key` 和参数哈希；
- Run、审批、Server 和 Tool 身份；
- 执行状态、尝试次数、恢复次数和乐观锁版本；
- Worker lease token、owner 和过期时间；
- 脱敏后的 API/Timeline 投影以及原始持久化结果；
- 自动工具调用的 Agent checkpoint 和完整性哈希。

成功或明确失败的相同逻辑调用会直接读取 Ledger 结果，不再访问远端。

## 远端幂等契约

Server 配置默认使用 `idempotency_mode: "none"`。这种模式下，如果 Worker 在网络请求后失联，CodeMate 无法确定远端是否已提交写入，因此不会自动重放。

只有远端 Server 明确实现幂等去重时，才可以配置：

```json
{
  "name": "tracker",
  "url": "https://mcp.example.com/mcp/",
  "allowed_tools": ["update_issue"],
  "tool_policies": {"update_issue": "approval_required"},
  "idempotency_mode": "metadata"
}
```

CodeMate 会在 MCP `tools/call` 请求的 `_meta` 中发送：

```json
{
  "codemate.io/idempotency-key": "<stable SHA-256 key>",
  "codemate.io/execution-id": "<ledger UUID>"
}
```

远端必须持久化 `idempotency-key → result`，相同 key 不得再次产生副作用。仅接收但忽略 `_meta` 不算支持幂等；错误声明会重新引入重复写入风险。

## Crash Recovery

远程调用前，CodeMate 会调度一个延迟 watchdog：

1. 正常完成后，watchdog 发现执行已结束并退出；
2. Worker 崩溃且 lease 过期时，watchdog 领取恢复任务；
3. `metadata` 模式在重试预算内使用完全相同的 key 自动恢复；
4. 其他模式进入 `unknown`，Run 变为 `waiting_reconciliation`；
5. 管理员确认远端实际结果后，Agent 从审批 checkpoint 或自动调用 checkpoint 继续。

网络超时也属于结果不确定。即使 Server 声明支持幂等，CodeMate 仍先显示 `unknown`，由管理员选择同 key 重试，避免无限自动重试。

## 配置

```env
MCP_EXECUTION_LEASE_SECONDS=60
MCP_EXECUTION_MAX_ATTEMPTS=3
MCP_EXECUTION_MAX_CHECKPOINT_CHARS=2000000
```

实际 lease 不会短于 `MCP_CLIENT_TIMEOUT_SECONDS + 5` 秒，防止 watchdog 在合法的长请求仍运行时提前接管。

RQ Worker 必须启用 scheduler；项目提供的 Worker 已默认启用。

## 管理 API

API 使用与 MCP 审批相同的管理员鉴权和 signed browser identity。

```bash
# 列出 Run 的执行账本
curl http://localhost:8000/mcp-executions/runs/<run_id> \
  -H "Authorization: Bearer ${EVALUATION_ADMIN_TOKEN}"

# 已在远端确认成功
curl -X POST http://localhost:8000/mcp-executions/<execution_id>/reconcile \
  -H "Authorization: Bearer ${EVALUATION_ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"action":"confirm_succeeded","expected_version":3,"note":"Verified remotely"}'

# 已确认失败
curl -X POST http://localhost:8000/mcp-executions/<execution_id>/reconcile \
  -H "Authorization: Bearer ${EVALUATION_ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"action":"confirm_failed","expected_version":3}'

# 仅 metadata 模式允许使用同一 key 重试
curl -X POST http://localhost:8000/mcp-executions/<execution_id>/reconcile \
  -H "Authorization: Bearer ${EVALUATION_ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"action":"retry","expected_version":3}'
```

如果对账已经保存但 Redis 暂时不可用，可调用 `POST /mcp-executions/<execution_id>/resume` 再次排队。所有对账操作使用 `expected_version` 防止并发覆盖，并写入安全审计和 Agent Timeline。

Server 健康指标、OpenTelemetry Trace、自动探活和 Circuit Breaker 见 [MCP Observability and Operations](mcp-operations.md)。
