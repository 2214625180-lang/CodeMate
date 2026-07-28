# MCP Sandbox Isolation、Egress Enforcement 与持续合规

## 架构

远程 MCP 协议连接不再由 Backend 或通用 Worker 直接建立：

```text
Backend / Worker
  -> authenticated HTTP, internal network
MCP Sandbox Broker
  -> authenticated CONNECT, internal network
MCP Egress Gateway
  -> DNS resolve + global-IP check + pinned TCP connection
Allowlisted MCP / OAuth host:443
```

Sandbox Broker 只加入 `mcp_isolated` internal network，没有默认互联网路由。它使用只读根文件系统、非 root UID、`cap_drop: ALL`、`no-new-privileges`、PID/CPU/内存限制，并且没有宿主机或持久卷挂载。Egress Gateway 是唯一同时加入 internal network 和外部网络的组件。

通用 Worker 和 `code-sandbox` Broker 都不再挂载 Docker Socket。Broker 只接收共享 Workspace、Broker Token、固定镜像和命令白名单配置，不接收数据库、KMS、MCP、SIEM 或管理员凭据；它重新推导测试命令后，通过 mTLS 和请求绑定的 Ed25519 工作负载身份调用独立 Firecracker/Kubernetes 执行平面。执行平面再次校验策略，并强制 microVM 或 Kata Job 隔离。详见 `docs/managed-sandbox-execution-plane.md`。

Bearer Token 只在 Backend/Worker 与 Broker 之间的认证请求中短暂传输；Gateway 仅看到 CONNECT hostname、port 和加密后的 TLS 字节，不接收 MCP Credential。Broker Token 与 Proxy Token 必须是不同的 32+ 字符 Secret Manager 值。

## 出站策略

Gateway 对每个 CONNECT 请求执行：

1. Basic Proxy Authentication；
2. 仅允许 `CONNECT`，拒绝明文 HTTP；
3. port 必须属于 `MCP_EGRESS_ALLOWED_PORTS`，staging/production 强制只能为 `443`；
4. hostname 必须精确匹配 `MCP_REGISTRY_ALLOWED_HOSTS`；
5. Gateway 自己解析 DNS，并拒绝 loopback、private、link-local、reserved 等所有非 global IP；
6. 直接连接本次验证得到的 IP，消除“校验后由客户端再次解析”的 DNS rebinding 窗口；
7. MCP Client、OAuth client-credentials 和 delegated OAuth refresh 全部禁用 redirect，并通过同一 Proxy。

允许列表必须覆盖 MCP Server、OAuth authorize/token endpoint 和 CodeMate OAuth callback hostname。不要使用宽泛域名后缀或通配符。

## 持续合规

`MCP_COMPLIANCE_ENABLED=true` 会通过 RQ 周期执行配置与运行态扫描。报告写入：

- `artifacts/compliance/mcp-compliance-latest.json`；
- `artifacts/compliance/history/<timestamp>-<sha256>.json`；
- Security Audit durable outbox，随后进入 SIEM 与 Object-Locked S3。

每份报告包含 canonical JSON SHA-256。Readiness 要求报告完整、状态为 `compliant` 且未超过 `MCP_COMPLIANCE_STALE_SECONDS`。运行态扫描同时验证 Broker attestation、Gateway TCP 可达性，并执行一次访问 `127.0.0.1:443` 的负向 canary，只有 Gateway 明确返回 403 才通过。

Operations Dashboard 支持查看控制项并触发扫描。管理员 API：

```text
GET  /mcp-operations/compliance/latest
POST /mcp-operations/compliance/scan
```

CI/staging 还会运行 `scripts/mcp_container_compliance.py`，验证 internal network、只读 rootfs、非 root、cap-drop、no-new-privileges 和无挂载约束。任一项失败都会阻止 qualification。

## Staging 配置

```dotenv
MCP_SANDBOX_ENABLED=true
MCP_SANDBOX_BROKER_TOKEN=<secret-manager-value>
MCP_EGRESS_PROXY_TOKEN=<different-secret-manager-value>
MCP_EGRESS_ALLOWED_PORTS=443
MCP_REGISTRY_ALLOWED_HOSTS=mcp.example.com,oauth.example.com,codemate.example.com
MCP_COMPLIANCE_ENABLED=true
MCP_COMPLIANCE_INTERVAL_SECONDS=300
MCP_COMPLIANCE_STALE_SECONDS=900
MCP_COMPLIANCE_RETENTION_DAYS=90
SANDBOX_EXECUTION_BROKER_TOKEN=<third-secret-manager-value>
```

真实 staging qualification 必须同时保留 container compliance JSON、runtime compliance JSON、负向 canary、压测和故障恢复证据。
