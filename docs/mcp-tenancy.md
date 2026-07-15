# Tenant-scoped MCP Authorization and Delegated User Identity

这一阶段把 CodeMate 的 MCP 调用从共享服务权限扩展为租户、仓库、主体和工具四层授权，并允许 Agent 使用用户委托的 OAuth 身份访问指定 MCP Server。

管理界面：

```text
http://localhost:3000/mcp-tenancy
```

## 授权模型

开启 `MCP_TENANT_AUTHORIZATION_ENABLED=true` 后采用 default-deny：

1. Repository 和 Agent Run 必须归属一个 Tenant；
2. Tenant 必须显式启用目标 MCP Server binding；
3. principal 必须命中 `discover`、`execute` 或 `approve` grant；
4. grant 可以限制到某个 Repository，也可以对 Tenant 全局生效；
5. `server_name` 和 `tool_name` 支持 `*`；
6. 有效的 `deny` 始终覆盖 `allow`，过期 grant 不参与判断；
7. 用户可通过 `(identity provider, subject)` Membership 获得 `admin`、`approver` 或 `member` role grant。

Agent 默认主体为 `agent:codemate-agent`。直连 `/mcp-client` API 的主体为 `service:mcp-client`。使用委托身份创建的 Agent Run 主体为 `user:<OAuth subject>`。

## 启用

```env
MCP_REGISTRY_ENABLED=true
MCP_REGISTRY_MASTER_KEY=<至少 32 字符的 Secret Manager/KMS 密钥>
MCP_TENANT_AUTHORIZATION_ENABLED=true
MCP_DEFAULT_TENANT_SLUG=default
MCP_DELEGATED_OAUTH_STATE_TTL_SECONDS=600
```

生产环境开启 Tenant Authorization 时必须同时开启 Dynamic Registry。首次启动会创建默认 Tenant，并把尚未归属 Tenant 的 Repository 和 Agent Run 回填到默认 Tenant。功能默认关闭，升级不会改变现有 MCP 行为。

建议按以下顺序配置：

1. 在 `/mcp-registry` 注册 Server 和 allowed tools；
2. 在 `/mcp-tenancy` 创建 Tenant 并绑定 Repository；
3. 为 Tenant 启用 Server binding；
4. 创建 agent、service、user 或 role grant；
5. 验证策略后再在生产环境开启开关。

## 租户绑定的 MCP Client 凭据

全局 `MCP_CLIENT_API_TOKEN` 只验证调用方可以访问 MCP Client API。开启租户授权后，还必须轮换并安全保存 Tenant Client Token，请求同时携带：

```http
Authorization: Bearer <MCP_CLIENT_API_TOKEN>
X-CodeMate-Tenant-ID: <tenant UUID>
X-CodeMate-Tenant-Token: <tenant client token>
X-CodeMate-Repo-ID: <optional repository UUID>
```

Tenant Client Token 只在轮换响应中返回一次，数据库仅保存 SHA-256 hash。持有全局 API Token 的调用方不能只靠伪造 Tenant ID 跨租户访问。

## Delegated User Identity

每个 Tenant/Server 可配置一个 OAuth Authorization Code Provider。授权流程使用：

- PKCE S256；
- 随机 state，数据库只保存 state hash；
- 有时效且只能消费一次的 OAuth state；
- AES-256-GCM 加密的 PKCE verifier、access token、refresh token 和 client secret；
- Token Endpoint HTTPS/host/private-network 校验且禁止 redirect；
- 到期前自动 refresh；
- 可立即撤销的 identity；
- 单独的 delegation proof，数据库仅保存 hash。

发起授权的浏览器用户必须已经是目标 Tenant 的 Membership。OAuth callback 返回 identity ID 和只展示一次的 delegation proof：

```json
{
  "identity": {"id": "<identity UUID>", "server_name": "docs"},
  "delegation_token": "<copy once>"
}
```

在 Bug Fix Agent 页面展开 “Delegated MCP identity”，填入两项即可；对应 API 请求为：

```json
{
  "issue": "Fix the failing integration",
  "test_command": "pytest",
  "delegated_identity_id": "<identity UUID>",
  "delegation_token": "<delegation proof>"
}
```

CodeMate 会验证 identity 未撤销、属于 Repository Tenant，并只把解密后的 access token 注入该 identity 绑定的 MCP Server。其他 Server 不会收到用户 Token。最终是否能发现、执行或审批工具仍由 Tenant grants 决定。

## 主要管理 API

所有管理 API 都位于 `/mcp-tenancy`，除 OAuth callback 外均使用 Evaluation 身份；策略变更要求 admin，发起自己的 OAuth 授权允许 viewer。

- `POST /tenants`：创建 Tenant；
- `PUT /tenants/{tenant_id}/repositories/{repo_id}`：绑定 Repository；
- `POST /tenants/{tenant_id}/client-token`：轮换 Tenant Client Token；
- `POST /tenants/{tenant_id}/memberships`：添加用户 Membership；
- `POST /tenants/{tenant_id}/bindings`：启用或禁用 Server；
- `POST /tenants/{tenant_id}/grants`：创建 allow/deny grant；
- `POST /tenants/{tenant_id}/oauth/providers`：配置 delegated OAuth provider；
- `POST /oauth/providers/{provider_id}/authorize`：开始当前用户授权；
- `GET /oauth/callback`：完成 code exchange；
- `POST /identities/{identity_id}/revoke`：撤销委托身份。

这些路由接入现有 signed browser identity、RBAC 和 security audit。响应和审计日志不会记录 client secret、OAuth token、PKCE verifier、Tenant Client Token 或 delegation proof。
