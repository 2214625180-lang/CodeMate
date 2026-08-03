# Development Configuration and Production Extensions

This guide keeps operational configuration out of the main portfolio narrative. The core product is the verifiable repair loop; the following capabilities are optional local-development setup or production deep dives.

## 1. Local development

```bash
cp .env.example .env
docker compose up --build
```

The default `.env.example` uses deterministic Mock LLM and embedding providers so ordinary development and tests do not require an API key. Use [`docs/demo-script.md`](demo-script.md) and `make demo` when presenting the real-model repair demo; its launcher rejects `LLM_PROVIDER=mock`.

### Real provider configuration

OpenAI chat and embeddings:

```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=384
OPENAI_API_KEY=sk-...
```

DeepSeek chat with OpenAI embeddings:

```env
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=sk-...
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

An OpenAI-compatible endpoint:

```env
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=your-chat-model
LLM_API_KEY=...

EMBEDDING_PROVIDER=openai-compatible
EMBEDDING_BASE_URL=https://your-provider.example/v1
EMBEDDING_MODEL=your-embedding-model
EMBEDDING_DIMENSION=1024
EMBEDDING_API_KEY=...
```

`EMBEDDING_DIMENSION` must match the vectors returned by the provider. Re-index repositories after changing the embedding provider, model, or dimension.

## 2. Evaluation access and RBAC

For a protected deployment, keep Evaluation tokens on the server-side frontend proxy. `EVALUATION_ADMIN_TOKEN` can read, run, and mutate Evaluation resources; `EVALUATION_CI_TOKEN` can read and trigger runs; `EVALUATION_READ_TOKEN` is read-only. Local development remains open when all three are empty.

The frontend can use `CODEMATE_EVALUATION_API_TOKEN` plus `FRONTEND_ADMIN_PASSWORD`. The backend validates signed proxy identity headers and a one-time nonce when `CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY=true`; multi-instance deployments should set `CODEMATE_PROXY_IDENTITY_NONCE_STORE=redis`.

Example role mapping:

```env
CODEMATE_RBAC_ADMIN_USERS=alice
CODEMATE_RBAC_ADMIN_TEAMS=my-org/platform-admins
CODEMATE_RBAC_VIEWER_ORGS=my-org
CODEMATE_PROXY_IDENTITY_SECRET=replace-with-a-32-character-minimum-secret
```

The detailed evaluation-gate contract is in [CI Evaluation Gate](ci-evaluation-gate.md).

## 3. Production extensions

These controls are intentionally secondary to the repair-agent story. They exist to support a deeper systems discussion after the core loop is clear.

| Extension | Why it exists | Primary document |
| --- | --- | --- |
| Dynamic MCP Registry and credential broker | Govern remote tool discovery and encrypted credentials | [MCP Registry](mcp-registry.md) |
| Tenant authorization, delegated identity, quotas, and approvals | Bound external tool access, cost, and user authority | [MCP tenancy](mcp-tenancy.md), [MCP Quotas](mcp-quotas.md), [MCP approvals](mcp-approval-workflow.md) |
| KMS envelope encryption and SIEM/S3 audit delivery | Preserve encrypted configuration and durable security evidence | [Staging qualification, KMS, and SIEM](staging-qualification-kms-siem.md) |
| MCP operations, health monitoring, circuit breakers, and compliance | Make policy enforcement observable and fail closed | [MCP Operations](mcp-operations.md), [MCP production readiness](mcp-production-readiness.md) |
| Managed Firecracker/Kubernetes execution plane | Separate local Docker convenience from production sandbox execution | [Managed sandbox execution plane](managed-sandbox-execution-plane.md) |

## 4. Safety boundary

The demo Compose overlay mounts a local Docker socket only into the worker so it can launch network-disabled test containers. This is a presentation convenience, not a production topology. Staging and production configuration require the remote sandbox broker/execution-plane controls described in [managed sandbox execution](managed-sandbox-execution-plane.md) and the qualification documents.
