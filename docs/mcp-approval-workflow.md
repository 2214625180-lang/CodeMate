# Human-in-the-loop MCP Approval Workflow

CodeMate 对本地策略为 `approval_required` 的 MCP 工具使用持久化审批工作流。模型只能提出调用，不能绕过审批、修改待审批参数或直接恢复 Agent。

## 状态流转

```text
Agent running
  → PlanMCPTools proposes approval_required tool
  → persist approval + Agent checkpoint
  → Run status: waiting_approval
  → human approve / reject
  → RQ resume job
  → revalidate checkpoint, policy, catalog, schema, argument hash
  → execute or create rejection observation
  → resume graph at ObserveMCP
  → Agent running / next approval / terminal status
```

审批状态：

```text
pending → queued → resuming → completed
                     ↘ reconciliation_required → queued
                              → failed
```

同一个 Run 同时只允许一个活动审批。Planner 一次提出多个审批工具时，只创建第一个请求，其余请求会以 `approval_deferred` 写入 Timeline，后续轮次可以重新规划。

## 配置

```env
MCP_APPROVAL_ENABLED=true
MCP_APPROVAL_TTL_SECONDS=1800
MCP_APPROVAL_RESUME_STALE_SECONDS=300
MCP_APPROVAL_MAX_CHECKPOINT_CHARS=2000000
MCP_EXECUTION_LEASE_SECONDS=60
MCP_EXECUTION_MAX_ATTEMPTS=3
```

需要审批的工具配置示例：

```env
MCP_CLIENT_SERVERS_JSON=[{"name":"tracker","url":"https://mcp.example.com/mcp/","bearer_token_env":"MCP_CLIENT_BEARER_TOKEN","allowed_tools":["search_issues","update_issue"],"tool_policies":{"search_issues":"auto","update_issue":"approval_required"}}]
```

生产环境还必须配置：

```env
EVALUATION_ADMIN_TOKEN=<至少 32 字符的管理 Token>
CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY=true
CODEMATE_PROXY_IDENTITY_SECRET=<独立随机密钥>
```

审批 API 复用现有管理员 RBAC 和 signed proxy identity。浏览器通过 Next.js 后端代理提交决定，不会获得管理 Token。

RQ Worker 使用 scheduler 处理审批过期任务。必须同时运行项目提供的 worker：

```bash
docker compose up --build
```

## API

列出 Run 的审批：

```bash
curl http://localhost:8000/mcp-approvals/runs/<run_id> \
  -H "Authorization: Bearer ${EVALUATION_ADMIN_TOKEN}"
```

批准并恢复：

```bash
curl -X POST http://localhost:8000/mcp-approvals/<approval_id>/decision \
  -H "Authorization: Bearer ${EVALUATION_ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"decision":"approve","expected_version":1,"note":"Reviewed"}'
```

拒绝并恢复：

```bash
curl -X POST http://localhost:8000/mcp-approvals/<approval_id>/decision \
  -H "Authorization: Bearer ${EVALUATION_ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"decision":"reject","expected_version":1,"note":"Unsafe external mutation"}'
```

如果决定已经持久化但 Redis 暂时不可用，可以重试恢复：

```bash
curl -X POST http://localhost:8000/mcp-approvals/<approval_id>/resume \
  -H "Authorization: Bearer ${EVALUATION_ADMIN_TOKEN}"
```

`expected_version` 用于乐观并发控制。使用旧版本提交相反决定会返回 `409`；相同决定可以安全重试。

## 执行前重新校验

批准不会直接等同于执行。Resume Worker 会再次验证：

- checkpoint SHA-256 完整性以及 Run/Repository 身份；
- 当前 Tool Catalog 中仍存在相同的 `server.tool`；
- 当前本地策略仍为 `approval_required`；
- 参数 SHA-256 与审批时完全一致；
- 参数仍然满足当前工具 JSON Schema；
- 审批没有过期；
- 当前恢复任务没有被其他 Worker 领取。
- Execution Ledger 中不存在已完成的相同幂等调用；若存在则直接复用结果。

任何一项失败都会阻止远程工具执行，并将安全拒绝作为 Observation 恢复 Agent。

## Timeline 和数据保护

Timeline 会显示：

- `approval_required`：待审批卡片、脱敏参数、策略和过期时间；
- `approval_decision`：审批人、决定和版本；
- `tool_call` / `tool_result`：批准后的实际调用；
- `observation`：恢复后的结果汇总。

参数键包含 `token`、`secret`、`password`、`authorization` 或 `api_key` 时，API 和 Timeline 会显示 `***redacted***`。数据库中的原始参数只用于审批后执行，决定 API 不接受参数修改。

远程调用本身由独立 Execution Ledger 管理。Worker 崩溃后的同 key 重试和人工对账流程见 [Durable MCP Execution Ledger](mcp-durable-execution.md)。
