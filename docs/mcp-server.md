# CodeMate 只读 MCP Server

CodeMate 可以通过 MCP Streamable HTTP 向 Codex、MCP Inspector 等客户端开放已索引仓库。MCP Server 只提供读取能力，不会写文件、应用补丁或执行命令。

## 启用服务

在 `.env` 中配置：

```env
MCP_ENABLED=true
MCP_AUTH_TOKEN=<至少 32 字符的随机 Token>
MCP_ALLOWED_REPO_IDS=
MCP_MAX_FILE_LINES=500
```

生成 Token：

```bash
openssl rand -hex 32
```

`MCP_ALLOWED_REPO_IDS` 为空时允许访问所有仓库。生产环境建议填写允许访问的仓库 UUID，多个 UUID 使用逗号分隔：

```env
MCP_ALLOWED_REPO_IDS=repo-uuid-1,repo-uuid-2
```

启动或重建服务：

```bash
docker compose up --build
```

MCP endpoint：

```text
http://localhost:8000/mcp/
```

如果启用了 MCP 但没有配置 Token，endpoint 会返回 `503`。Token 缺失或错误时返回 `401`。生产环境启用 MCP 时，应用启动检查要求 Token 至少包含 32 个字符。

## 可用工具

所有工具都带有 MCP `readOnlyHint=true` 标注。

| 工具 | 用途 |
| --- | --- |
| `list_repositories` | 列出当前 Token 范围内的仓库 |
| `search_code` | 对已索引仓库执行混合代码检索 |
| `list_files` | 列出仓库文件和基础元数据 |
| `read_file` | 按行读取文件，受 `MCP_MAX_FILE_LINES` 限制 |
| `get_repo_memory` | 读取仓库结构摘要和缓存记忆 |
| `inspect_ci` | 读取 CI 配置并预览生成的 workflow，不写入文件 |
| `get_run_status` | 读取已有 Agent Run 的状态和结果摘要 |

仓库白名单同时作用于仓库、文件、搜索和 Agent Run 查询。未授权仓库和不存在的仓库都会返回相同的 `Repository not available`，避免泄漏仓库是否存在。

## Codex 客户端配置

先让启动 Codex 的 shell 能读取 Token：

```bash
export CODEMATE_MCP_TOKEN='<与服务端 MCP_AUTH_TOKEN 相同的值>'
```

使用 Codex CLI 添加 Streamable HTTP Server：

```bash
codex mcp add codemate \
  --url http://localhost:8000/mcp/ \
  --bearer-token-env-var CODEMATE_MCP_TOKEN
```

检查配置：

```bash
codex mcp get codemate
codex mcp list
```

Codex 保存的是环境变量名称，不会把 Token 写入 MCP 配置。后续启动 Codex 时仍需保证 `CODEMATE_MCP_TOKEN` 存在于进程环境中。

## MCP Inspector 验证

列出工具：

```bash
npx @modelcontextprotocol/inspector --cli http://localhost:8000/mcp/ \
  --transport http \
  --method tools/list \
  --header "Authorization: Bearer ${MCP_AUTH_TOKEN}"
```

调用仓库列表工具：

```bash
npx @modelcontextprotocol/inspector --cli http://localhost:8000/mcp/ \
  --transport http \
  --method tools/call \
  --tool-name list_repositories \
  --header "Authorization: Bearer ${MCP_AUTH_TOKEN}"
```

## 安全说明

- 不要把 `MCP_AUTH_TOKEN` 提交到 Git；`.env.example` 只保留空值。
- 对外部署时应使用 HTTPS，并在反向代理处配置请求大小限制和访问日志。
- 生产环境应配置 `MCP_ALLOWED_REPO_IDS`，遵循最小权限原则。
- 当前 Bearer Token 是服务身份认证 MVP。需要多用户登录、动态授权或第三方客户端发现时，可升级为 MCP OAuth 2.1 Resource Server。

