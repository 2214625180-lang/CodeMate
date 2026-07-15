# CodeMate 作为 MCP Client

CodeMate 可以连接外部 Streamable HTTP MCP Server，发现并调用管理员允许的工具，也可以在 Fix Agent 的诊断阶段把指定工具的结果作为外部上下文。

Server 可以由部署管理员通过环境变量静态配置，也可以通过 Dynamic Registry Dashboard 管理。Registry 强制 HTTPS、SSRF 防护、加密凭据和配置审计，详情见 [Dynamic MCP Server Registry and Credential Broker](mcp-registry.md)。目前仍不支持 stdio MCP Server。

## 配置

```env
MCP_CLIENT_ENABLED=true

# 保护 CodeMate /mcp-client API，不会发送给远程 Server。
MCP_CLIENT_API_TOKEN=<使用 openssl rand -hex 32 生成>

# 远程 MCP Server 的凭据。
MCP_CLIENT_BEARER_TOKEN=<远程 Server Token>

MCP_CLIENT_TIMEOUT_SECONDS=20
MCP_CLIENT_MAX_RESULT_CHARS=50000
MCP_TOOL_ROUTER_ENABLED=true
MCP_TOOL_ROUTER_MAX_ROUNDS=2
MCP_TOOL_ROUTER_MAX_CALLS_PER_RUN=4
MCP_TOOL_ROUTER_MAX_CATALOG_TOOLS=64

MCP_CLIENT_SERVERS_JSON=[{"name":"docs","url":"https://mcp.example.com/mcp/","bearer_token_env":"MCP_CLIENT_BEARER_TOKEN","allowed_tools":["search_docs"],"tool_policies":{"search_docs":"auto"}}]
```

配置字段：

| 字段 | 含义 |
| --- | --- |
| `name` | Server 唯一名称，只允许字母、数字、`_`、`-` |
| `url` | Streamable HTTP endpoint，只接受 HTTP(S) URL |
| `bearer_token_env` | 保存远程 Bearer Token 的环境变量名称，不是 Token 本身 |
| `allowed_tools` | CodeMate 可以调用的工具白名单；空数组表示禁止调用任何工具 |
| `tool_policies` | Agent 对每个工具的本地执行策略 |
| `agent_context_tools` | 可选的固定预取工具；动态 Router 通常不需要配置 |
| `idempotency_mode` | `none`（默认）或远端明确支持的 `metadata` 幂等契约 |
| `enabled` | 是否启用该 Server，默认 `true` |

策略支持：

- `auto`：Policy Engine 校验通过后允许 Agent 自动执行。只应授予安全、可重复的只读工具。
- `approval_required`：模型可以提出调用，Agent 持久化 checkpoint 并等待管理员批准或拒绝。
- `deny`：禁止 Agent 执行。工具未配置策略时默认也是 `deny`。

本地策略是最终权限来源，不信任远程 MCP Server 的 `readOnlyHint`。`agent_context_tools` 中的工具必须同时出现在 `allowed_tools`，并明确配置为 `auto`。参数值支持递归替换：

- `{issue}`：Fix Run 的问题描述。
- `{repo_id}`：当前 CodeMate 仓库 ID。

远程 MCP 结果会被标记为不可信数据。调用失败会写入 Agent Timeline，但不会中断 Fix Run。

## 动态 Tool Router

启用后，Fix Agent 在本地诊断之后进入受控循环：

```text
Discover Tool Catalog
  → PlanMCPTools
  → Policy + JSON Schema validation
  → CallMCPTools
  → ObserveMCP
  → 再规划或 GeneratePatch
```

Tool Catalog 使用 `server_name.tool_name` 作为全局名称。Planner 只能提出计划，不能决定权限；Policy Engine 会重新检查：

- 工具是否来自本次发现的 Catalog。
- 工具是否在 `allowed_tools` 中。
- 本地策略是否为 `auto`。
- 参数是否通过工具的 JSON Schema。
- 是否存在禁止的外部 `$ref`。
- 是否超过轮次和总调用预算。
- 是否与当前或之前轮次的调用完全重复。

每次计划、策略拒绝、工具调用、工具结果和 Observation 都会写入 Agent Timeline。远程工具描述和结果按不可信数据处理，不能覆盖系统指令。

需要修改外部状态的工具应配置为 `approval_required`。完整暂停、审批、恢复和过期流程见 [Human-in-the-loop MCP Approval Workflow](mcp-approval-workflow.md)。

所有动态工具调用都会经过持久化执行账本。写工具的幂等键、租约和崩溃恢复约束见 [Durable MCP Execution Ledger](mcp-durable-execution.md)。

Docker Compose 已透传 `MCP_CLIENT_BEARER_TOKEN`。如果需要为多个 Server 使用不同的 Token 环境变量，需要在 `backend` 和 `worker` 的 `environment` 中显式透传这些变量。

修改配置后重建服务：

```bash
docker compose up --build
```

## Client API

所有 `/mcp-client` 请求使用独立的 API Token：

```bash
export CODEMATE_MCP_CLIENT_TOKEN='<MCP_CLIENT_API_TOKEN>'
```

读取配置的 Server：

```bash
curl http://localhost:8000/mcp-client/servers \
  -H "Authorization: Bearer ${CODEMATE_MCP_CLIENT_TOKEN}"
```

连接 Server 并读取协议版本、Server 信息和 capabilities：

```bash
curl http://localhost:8000/mcp-client/servers/docs \
  -H "Authorization: Bearer ${CODEMATE_MCP_CLIENT_TOKEN}"
```

发现工具：

```bash
curl http://localhost:8000/mcp-client/servers/docs/tools \
  -H "Authorization: Bearer ${CODEMATE_MCP_CLIENT_TOKEN}"
```

工具列表会同时返回远程 Server 的 schema、annotations，以及 CodeMate 本地 allowlist 计算出的 `allowed` 状态。

调用允许的工具：

```bash
curl -X POST http://localhost:8000/mcp-client/servers/docs/call \
  -H "Authorization: Bearer ${CODEMATE_MCP_CLIENT_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"search_docs","arguments":{"query":"How does authentication work?"}}'
```

未进入 `allowed_tools` 的调用返回 `403`；远程连接或协议错误返回 `502`；Client 未启用或配置错误返回 `503`。

## 安全边界

- Server URL 只能通过部署配置添加，API 调用方不能提交任意 URL。
- `allowed_tools` 是强制执行的本地权限，不依赖远程 Server 的 `readOnlyHint`。
- Agent 自动调用仅限本地策略明确为 `auto` 的工具；固定预取还必须列入 `agent_context_tools`。
- 请求参数限制为 100000 字符，响应受 `MCP_CLIENT_MAX_RESULT_CHARS` 限制。
- 生产环境启用 Client API 时，`MCP_CLIENT_API_TOKEN` 至少需要 32 个字符。
- 生产环境应只连接 HTTPS endpoint，并对远程 MCP Server 使用最小权限凭据。
