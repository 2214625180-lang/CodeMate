# MCP Observability and Operations

CodeMate 提供持久化 MCP 运维控制面，用于观察远端 Server 健康、工具执行指标、崩溃恢复、未知结果积压以及 Circuit Breaker 状态。

动态 Server 配置与加密凭据管理见 [Dynamic MCP Server Registry and Credential Broker](mcp-registry.md)。

Dashboard 地址：

```text
http://localhost:3000/mcp-operations
```

Dashboard 和 `/mcp-operations` API 使用与审批、Execution Ledger 相同的管理员 RBAC、服务 Token 和 signed browser identity。浏览器不会获得后端管理 Token。

## 能力

- 按 Server 和 Tool 聚合调用量、成功、失败、`unknown` 和请求速率；
- P50、P95、P99 执行延迟；
- 幂等命中、Crash Recovery、待审批和执行中数量；
- 自动 Streamable HTTP 探活、协议版本和 Server 信息；
- 持久化 `closed → open → half_open → closed` Circuit Breaker；
- 手动打开、关闭、重置 Circuit；
- 未对账执行、错误率、Server 不健康和 Circuit Open 告警；
- Prometheus exposition；
- OpenTelemetry MCP 调用和健康探测 Span。

所有指标标签只包含 Server、Tool、Run、Approval 和 Execution ID，不记录工具参数、Token 或远端结果。

## Circuit Breaker

```text
closed
  └─ transport failures >= threshold → open
open
  ├─ request before cooldown → reject without remote call
  └─ cooldown elapsed → half_open
half_open
  ├─ one trial succeeds → closed
  └─ trial fails → open
```

只有连接、协议和超时异常累计传输失败。远端正常返回的 Tool Error 表明 MCP 通道可用，不会错误触发 Server 熔断。

Circuit 状态存储在数据库中，因此多个 Worker 和服务重启共享同一状态。半开状态只允许一个有租约的试探调用。管理员手动打开的 Circuit 不会因 cooldown 或健康探测自动关闭。

被 Circuit 拒绝的调用不会访问远端，Execution Ledger 会保存明确的 `mcp_circuit_open` 失败结果。

## Health Monitoring

API 启动时会安排第一个探活任务；RQ Worker 完成探活后继续调度下一轮。Worker 必须保持 scheduler 开启，项目提供的 Worker 已配置 `with_scheduler=True`。

自动探活失败会更新健康状态，并与真实调用的传输失败共同驱动 Circuit。健康探测成功可以关闭非人工打开的 Circuit。

```env
MCP_HEALTH_MONITOR_ENABLED=true
MCP_HEALTH_PROBE_INTERVAL_SECONDS=60
MCP_HEALTH_STALE_SECONDS=180
```

## Circuit 和告警配置

```env
MCP_OBSERVABILITY_WINDOW_MINUTES=60
MCP_CIRCUIT_BREAKER_ENABLED=true
MCP_CIRCUIT_FAILURE_THRESHOLD=3
MCP_CIRCUIT_COOLDOWN_SECONDS=60
MCP_CIRCUIT_HALF_OPEN_LEASE_SECONDS=30
MCP_ALERT_UNKNOWN_AGE_SECONDS=300
MCP_ALERT_ERROR_RATE_THRESHOLD=0.5
MCP_ALERT_MINIMUM_CALLS=5
```

## OpenTelemetry

启用 OTLP HTTP Trace Exporter：

```env
OTEL_ENABLED=true
OTEL_SERVICE_NAME=codemate-backend
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318/v1/traces
```

`mcp.tools.call` Span 包含：

- `mcp.server`、`mcp.tool`、`mcp.qualified_name`；
- `mcp.execution_id`、`mcp.run_id`、`mcp.approval_id`；
- `mcp.idempotency_mode` 和 attempt；
- 传输异常与状态。

`mcp.health_probe` Span 记录 Server 和探活异常。

## API

```bash
# Dashboard 数据
curl 'http://localhost:8000/mcp-operations/overview?window_minutes=60' \
  -H "Authorization: Bearer ${EVALUATION_ADMIN_TOKEN}"

# Prometheus
curl http://localhost:8000/mcp-operations/metrics/prometheus \
  -H "Authorization: Bearer ${EVALUATION_ADMIN_TOKEN}"

# 探测所有 Server
curl -X POST http://localhost:8000/mcp-operations/probes \
  -H "Authorization: Bearer ${EVALUATION_ADMIN_TOKEN}"

# 探测一个 Server
curl -X POST http://localhost:8000/mcp-operations/servers/tracker/probe \
  -H "Authorization: Bearer ${EVALUATION_ADMIN_TOKEN}"

# 人工打开 Circuit；expected_version 来自 overview/servers
curl -X POST http://localhost:8000/mcp-operations/servers/tracker/circuit \
  -H "Authorization: Bearer ${EVALUATION_ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"action":"open","expected_version":3}'
```

Circuit 控制支持 `open`、`close`、`reset`。`expected_version` 提供乐观并发控制，旧版本操作返回 `409`。所有运维 API 操作写入安全审计日志。
