# Dynamic MCP Server Registry and Credential Broker

CodeMate 支持通过数据库和管理 Dashboard 动态注册外部 MCP Server。Agent、MCP Client API 和 Health Monitor 在创建 Client 时合并静态配置与动态 Registry，因此新增、禁用、修改策略或轮换凭据后不需要重启服务。

Dashboard：

```text
http://localhost:3000/mcp-registry
```

## 功能

- 动态注册、更新、启用、禁用和删除 Streamable HTTP Server；
- 本地 `allowed_tools`、`auto / approval_required / deny` 策略；
- 在线连接验证、协议版本、Capabilities 和 Tool Schema 快照；
- 配置版本历史、操作者记录和乐观锁回滚；
- Bearer Token 和 OAuth2 Client Credentials；
- AES-256-GCM 凭据静态加密；
- OAuth Access Token 缓存、过期刷新和错误状态；
- 主密钥 previous-key 轮换与批量 rewrap；
- HTTPS、Host Allowlist、私网地址拦截和连接前 DNS 检查；
- 管理员 RBAC、signed browser identity 和安全审计；
- API/浏览器响应永不返回 Token、Client Secret 或解密后的凭据。

## 配置

```env
MCP_REGISTRY_ENABLED=true
MCP_REGISTRY_MASTER_KEY=<openssl rand -hex 32>
MCP_REGISTRY_KEY_VERSION=1
MCP_REGISTRY_MAX_SERVERS=64
MCP_REGISTRY_ALLOWED_HOSTS=
MCP_REGISTRY_ALLOW_PRIVATE_NETWORKS=false
MCP_REGISTRY_REQUIRE_HTTPS=true
MCP_OAUTH_TOKEN_EXPIRY_SKEW_SECONDS=60
```

生产环境启用 Registry 时，`MCP_REGISTRY_MASTER_KEY` 至少需要 32 个字符。每个环境应使用独立密钥，并通过 Secret Manager/KMS 注入，不能提交到仓库。

`MCP_REGISTRY_ALLOWED_HOSTS` 非空时，动态 Server 和 OAuth Token Endpoint 的 Host 必须在逗号分隔的 Allowlist 内。默认拒绝 localhost、`.local`、私网、回环、链路本地和其他非全局 IP。

开发环境确实需要连接本地 Server 时才可以设置：

```env
MCP_REGISTRY_REQUIRE_HTTPS=false
MCP_REGISTRY_ALLOW_PRIVATE_NETWORKS=true
```

不得在生产环境使用这两个放宽项。

## Credential Broker

Bearer Token 只在远程请求前解密并写入进程内请求 Header。数据库保存：

```text
base64(nonce || AES-256-GCM(ciphertext, aad="codemate-mcp-credential-v1"))
```

OAuth2 Client Credentials 保存 `token_url`、`client_id`、`client_secret` 和 scopes。Access Token 会加密缓存，并在到期前按 `MCP_OAUTH_TOKEN_EXPIRY_SKEW_SECONDS` 提前刷新。Token Endpoint 不允许重定向，避免凭据通过跳转泄漏。

### 主密钥轮换

1. 把旧密钥设置为 `MCP_REGISTRY_PREVIOUS_MASTER_KEY`；
2. 将新密钥设置为 `MCP_REGISTRY_MASTER_KEY`；
3. 增加 `MCP_REGISTRY_KEY_VERSION`；
4. 重启服务；
5. 调用 `POST /mcp-registry/credentials/rewrap`；
6. 验证所有凭据后删除 previous key 并再次重启。

## API 示例

```bash
# 注册 Server
curl -X POST http://localhost:8000/mcp-registry/servers \
  -H "Authorization: Bearer ${EVALUATION_ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name":"tracker",
    "url":"https://mcp.example.com/mcp",
    "allowed_tools":["search_issue","update_issue"],
    "tool_policies":{"search_issue":"auto","update_issue":"approval_required"},
    "idempotency_mode":"metadata"
  }'

# 设置 Bearer Token
curl -X PUT http://localhost:8000/mcp-registry/servers/<server_id>/credential \
  -H "Authorization: Bearer ${EVALUATION_ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"auth_type":"bearer","token":"<secret>"}'

# 设置 OAuth2 Client Credentials
curl -X PUT http://localhost:8000/mcp-registry/servers/<server_id>/credential \
  -H "Authorization: Bearer ${EVALUATION_ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "auth_type":"oauth2_client_credentials",
    "token_url":"https://identity.example.com/oauth/token",
    "client_id":"codemate",
    "client_secret":"<secret>",
    "scopes":["mcp.call"]
  }'

# 验证连接并保存 Capability/Tool 快照
curl -X POST http://localhost:8000/mcp-registry/servers/<server_id>/validate \
  -H "Authorization: Bearer ${EVALUATION_ADMIN_TOKEN}"
```

静态 `MCP_CLIENT_SERVERS_JSON` 仍然受支持。动态 Server 不能使用与静态配置相同的名称，避免无意覆盖部署管理员配置。
