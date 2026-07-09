# CodeMate

中文 | [English](README.en.md)

CodeMate 是一个小而完整的 AI 代码工程平台。它可以把 TypeScript、JavaScript、Python、Vue 仓库索引成语义代码块，基于文件和行号引用回答代码问题，运行 LangGraph 修复 Agent，在沙箱中验证补丁，并通过 Evaluation Center、后端 RBAC 和审计日志持续衡量与保护系统行为。

## 项目亮点

- 可引用的代码 RAG：AST/SFC 语义分块、关键词/向量混合召回、确定性 rerank、同文件上下文扩展、多仓库 SSE 问答。
- Agent 修复闭环：LangGraph 串联 parse、retrieve、read、diagnose、patch、test、reflect、final 节点，前端展示 Timeline 和 Diff Viewer。
- 沙箱验证：临时 workspace、`git apply` 应用补丁、命令白名单、CPU/内存/超时限制、默认 `--network none`，并预留 gVisor 和 Firecracker runner。
- 评测体系：retrieval/fix 数据集、快照、运行记录、产物、历史对比、CI gate 脚本和 GitHub Actions 集成。
- Evaluation 安全加固：前端 RBAC + 后端 RBAC、signed proxy identity、nonce replay 防护、分权 service token、key rotation、生产配置校验和后端审计日志。
- 面试讲解材料：[技术难点与取舍](docs/technical-challenges-tradeoffs.md)。

## 文档

- [Demo 脚本](docs/demo-script.md)
- [CI Evaluation Gate](docs/ci-evaluation-gate.md)
- [技术难点与取舍](docs/technical-challenges-tradeoffs.md)

## 系统架构

```text
Frontend: Next.js 14 + TypeScript + TailwindCSS
  - 仓库列表/详情
  - 带引用的代码问答
  - Bug Fix 页面
  - Agent Timeline
  - Diff Viewer

Backend: FastAPI + SQLAlchemy + RQ
  - Repo Service
  - Index Service
  - Retrieval Service
  - Chat Service
  - Repo Memory Service
  - CI Service
  - LangGraph Agent Service
  - Docker Sandbox Service
  - Trace/Feedback APIs

Storage and infra:
  - PostgreSQL: repository、files、chunks、runs、steps、evaluations
  - Qdrant: chunk embeddings 和 payload metadata
  - Redis/RQ: 后台索引和 Agent job
  - Docker: 本地服务和沙箱测试 runner
```

## 技术栈

- Frontend: Next.js 14、TypeScript、TailwindCSS
- Backend: FastAPI、Python 3.11、SQLAlchemy
- Agent: LangGraph
- Queue: Redis + RQ
- Database: PostgreSQL
- Vector DB: Qdrant
- Sandbox: worker 容器内通过 Docker CLI 启动测试容器
- Providers: 默认 mock；支持 OpenAI-compatible LLM 和 embedding provider

## 本地启动

```bash
cp .env.example .env
docker compose up --build
```

打开：

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health
- Qdrant: http://localhost:6333

如果 Docker Hub 拉取镜像时出现 `auth.docker.io ... timeout`，等网络稳定后重试，或提前拉取基础镜像：

```bash
docker pull python:3.11-slim
docker pull node:20-alpine
docker pull postgres:16-alpine
docker pull redis:7-alpine
docker pull qdrant/qdrant:v1.9.5
```

## Provider 配置

默认 `.env.example` 使用 `LLM_PROVIDER=mock` 和 `EMBEDDING_PROVIDER=mock`，因此本地启动不需要 API key。

OpenAI chat + embeddings:

```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=384
OPENAI_API_KEY=sk-...
```

DeepSeek chat + OpenAI embeddings:

```env
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=sk-...
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

自定义 OpenAI-compatible endpoint:

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

`EMBEDDING_DIMENSION` 必须和模型实际返回的向量维度一致。对于 `text-embedding-3-*`，CodeMate 会把配置的维度传给 API；其他 embedding 模型需要把该值改成 provider 返回的真实维度。

修改 `EMBEDDING_PROVIDER`、`EMBEDDING_MODEL` 或 `EMBEDDING_DIMENSION` 后，需要重新索引相关仓库，让 Qdrant 使用新模型重建向量。CodeMate 的 embedding 文本会包含文件路径、语言、符号元数据、imports、exports 和 chunk 内容。

Retrieval 调参：

```env
RETRIEVAL_TOP_K=8
RETRIEVAL_MIN_VECTOR_SCORE=0.72
RETRIEVAL_CANDIDATE_MULTIPLIER=4
RETRIEVAL_RERANK_ENABLED=true
RETRIEVAL_CONTEXT_EXPANSION_ENABLED=true
RETRIEVAL_CONTEXT_WINDOW=1
RETRIEVAL_CONTEXT_MAX_EXTRA=4
MULTI_REPO_TOP_K=12
MULTI_REPO_MAX_REPOS=8
```

检索流程会执行关键词/向量混合召回、确定性 rerank 和 same-file context expansion。上下文扩展会把高置信命中的父级或相邻 chunk 一起带入提示词，同时保留精确 citation 范围。

Repo Memory 和 CI 生成：

```env
REPO_MEMORY_MAX_FILES=12
REPO_MEMORY_MAX_SYMBOLS=30
CI_WORKFLOW_FILENAME=codemate-ci.yml
```

Repo Memory 会在索引成功后刷新，也可以手动刷新。CI inspection 会识别常见本地 CI 配置，并为 Node/Python 项目生成 GitHub Actions workflow。

## Demo 仓库

创建一个小 JavaScript 仓库：

```text
demo-bug-repo/
  package.json
  src/math.js
  test/math.test.js
```

`package.json`:

```json
{
  "scripts": {
    "test": "node --test"
  },
  "type": "module"
}
```

`src/math.js`:

```js
export function add(a, b) {
  return a - b;
}
```

`test/math.test.js`:

```js
import assert from "node:assert/strict";
import test from "node:test";
import { add } from "../src/math.js";

test("add sums two numbers", () => {
  assert.equal(add(2, 3), 5);
});
```

提交仓库，并把它暴露成后端可以 clone 的 Git URL。

## 仓库索引

```bash
curl -X POST http://localhost:8000/repos \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/your-user/demo-bug-repo.git"}'
```

查看状态：

```bash
curl http://localhost:8000/repos/<repo_id>/status
```

预期状态流转：

```text
pending -> cloning -> parsing -> embedding -> indexed
```

默认增量重建索引。CodeMate 会更新 workspace，比较已索引文件 hash 和当前 checkout，删除被移除或变更文件的向量，只重新 embedding 新增或变更 chunk。需要全量重建时：

```bash
curl -X POST "http://localhost:8000/repos/<repo_id>/reindex?full=true"
```

读取或刷新 Repo Memory：

```bash
curl http://localhost:8000/repos/<repo_id>/memory

curl -X POST http://localhost:8000/repos/<repo_id>/memory/refresh
```

检查或写入 CI workflow：

```bash
curl http://localhost:8000/repos/<repo_id>/ci

curl -X POST http://localhost:8000/repos/<repo_id>/ci/workflow
```

检查 Qdrant：

```bash
curl http://localhost:6333/collections/codemate_chunks

curl -X POST http://localhost:6333/collections/codemate_chunks/points/scroll \
  -H "Content-Type: application/json" \
  -d '{"limit":3,"with_payload":true,"with_vector":false}'
```

## 代码问答

Frontend:

```text
/repos/<repo_id>/chat
```

API:

```bash
curl -N -X POST http://localhost:8000/repos/<repo_id>/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"add 函数在哪里？"}'
```

多仓库问答：

```text
/repos/chat
```

```bash
curl -N -X POST http://localhost:8000/repos/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"认证逻辑在哪些仓库里？","repo_ids":["repo-a","repo-b"]}'
```

如果省略 `repo_ids`，CodeMate 会在已索引仓库中检索，最多覆盖 `MULTI_REPO_MAX_REPOS` 个仓库。多仓库 citation 会包含 `repo_id` 和 `repo_name`，前端可以打开正确 workspace 中的代码片段。

SSE stream 事件：

```text
token
citation
done
error
```

如果检索无结果，系统会返回：

```text
未在当前索引中找到相关代码。
```

## Bug Fix Agent

Frontend:

```text
/repos/<repo_id>/fix
```

API:

```bash
curl -X POST http://localhost:8000/repos/<repo_id>/fix \
  -H "Content-Type: application/json" \
  -d '{"issue":"add function test fails: expected 5 but received -1","test_command":"npm test"}'
```

轮询运行结果：

```bash
curl http://localhost:8000/runs/<run_id>
```

流式查看 trace：

```bash
curl -N http://localhost:8000/runs/<run_id>/trace
```

提交反馈：

```bash
curl -X POST http://localhost:8000/runs/<run_id>/feedback \
  -H "Content-Type: application/json" \
  -d '{"status":"accepted"}'
```

Trace 事件：

```text
plan
tool_call
tool_result
patch
test_result
reflection
final
error
```

前端 Timeline 只展示可解释事件，不暴露模型隐藏 chain-of-thought。

## PR Review

Frontend:

```text
/repos/<repo_id>/review
```

Review 粘贴的 diff：

```bash
curl -X POST http://localhost:8000/repos/<repo_id>/review \
  -H "Content-Type: application/json" \
  -d '{"diff":"diff --git a/src/app.ts b/src/app.ts\n...","question":"Focus on correctness and tests"}'
```

Review 已索引 workspace 中的 ref：

```bash
curl -X POST http://localhost:8000/repos/<repo_id>/review \
  -H "Content-Type: application/json" \
  -d '{"base_ref":"origin/main","head_ref":"origin/feature"}'
```

响应会包含 summary、changed files、结构化 findings，以及从仓库上下文检索到的 citations。

## 沙箱说明

- 临时 workspace 创建在 `SANDBOX_WORKSPACE_DIR` 下。
- `.env*`、`node_modules`、build output 和 coverage 目录会被排除。
- 补丁通过 `git apply` 应用。
- 测试命令必须出现在 `SANDBOX_ALLOWED_COMMANDS` 中。
- Docker 测试默认设置 CPU、内存、timeout 限制，并使用 `--network none`。
- `SANDBOX_RUNTIME=docker` 使用标准 Docker runtime。
- `SANDBOX_RUNTIME=gvisor` 会给 Docker 增加 `--runtime ${SANDBOX_GVISOR_DOCKER_RUNTIME}`，默认值是 `runsc`。
- `SANDBOX_RUNTIME=firecracker` 会执行 `SANDBOX_FIRECRACKER_COMMAND_TEMPLATE`，通过外部 Firecracker runner 处理 `{workspace}`、`{image}`、`{command}` 和 `{timeout}`。
- worker 挂载 `/var/run/docker.sock`，用于启动沙箱容器。
- Docker Compose 下，`backend/sandbox-runs` 在 host 和 worker 中保持相同绝对路径，因为 Docker bind mount 由 Docker daemon 解析。

## Evaluation

远程或 CI 使用时，至少配置一个后端 Evaluation service token 来保护 Evaluation API。`EVALUATION_ADMIN_TOKEN` 可以读取、运行和变更 Evaluation 资源；`EVALUATION_CI_TOKEN` 可以读取 Evaluation 资源并触发评测 run，但不能创建、更新、删除或 backfill benchmark dataset；`EVALUATION_READ_TOKEN` 只能读取 Evaluation 资源。CLI 脚本会自动发送 `CODEMATE_EVALUATION_API_TOKEN`，也可以显式传 `--api-token`。CI 场景建议把 `EVALUATION_CI_TOKEN` 写入 `CODEMATE_EVALUATION_API_TOKEN`。如果所有 Evaluation service token 都为空，本地开发会保持开放。

当前端部署到受保护的 Evaluation API 前面时，把后端 token 保存在服务端：在 frontend server 上设置 `CODEMATE_EVALUATION_API_TOKEN`，并用 `FRONTEND_ADMIN_PASSWORD` 保护 Evaluation Center。浏览器只访问同源 Next.js proxy，后端 token 不会进入 client-side code。Proxy 会转发服务端 token，同时附带可信的 `X-CodeMate-Evaluation-Role`、`X-CodeMate-Evaluation-User` 和 `X-CodeMate-Evaluation-Provider` header，让后端执行同样的 viewer/admin RBAC 判断。

这些身份 header 必须包含：

```text
X-CodeMate-Evaluation-Identity-Timestamp
X-CodeMate-Evaluation-Identity-Nonce
X-CodeMate-Evaluation-Identity-Signature
```

后端会基于 request method、path/query、timestamp、nonce、role、user、provider 验证 HMAC，验证通过后才信任 proxy 转发的身份。每个 nonce 会在 `CODEMATE_PROXY_IDENTITY_TTL_SECONDS` 内消费一次，重复使用会被拒绝。前后端服务需要设置相同的 `CODEMATE_PROXY_IDENTITY_SECRET`。

Key rotation 时，后端把新值放在 `CODEMATE_PROXY_IDENTITY_SECRET`，旧值保留在 `CODEMATE_PROXY_IDENTITY_PREVIOUS_SECRET`，直到所有 frontend instance 都使用新 key 签名。如果没有显式配置 current secret，系统会为了兼容使用 evaluation API token 作为签名 key；生产部署建议使用独立 secret，避免持有 API token 的调用方伪造用户身份 header。

多进程或多实例后端应使用 `CODEMATE_PROXY_IDENTITY_NONCE_STORE=redis`；`memory` 只适合单进程本地开发。直接 CI/script 调用只带后端 token 时，会按 token 对应的 service scope 执行。设置 `CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY=true` 后，frontend proxy 请求和直接 browser-like 请求都必须携带 signed identity，同时保留非浏览器 service token path 给 CI 使用。`APP_ENV=production` 时，`CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY` 必须显式设置为 `true` 或 `false`，避免生产环境静默继承本地默认值。

团队访问可以配置 GitHub OAuth app callback，例如：

```text
https://your-frontend.example.com/api/auth/github/callback
```

然后设置：

```env
GITHUB_OAUTH_CLIENT_ID=...
GITHUB_OAUTH_CLIENT_SECRET=...
CODEMATE_RBAC_ADMIN_USERS=alice
CODEMATE_RBAC_ADMIN_TEAMS=my-org/platform-admins
CODEMATE_RBAC_VIEWER_ORGS=my-org
```

Admin 用户和团队可以运行 evaluations 并变更 benchmark datasets。Viewer 用户、viewer teams 和 viewer org 成员可以查看 runs、artifacts、history、compare reports 和 gate results。

安全敏感的前后端 Evaluation 事件会以 JSONL 写入 `SECURITY_AUDIT_LOG_PATH`，默认路径是 `artifacts/security/events.jsonl`。日志会记录 login attempts、OAuth/RBAC decisions、proxy authorization decisions、Evaluation API proxy calls、带解析后用户 role/provider 的后端 Evaluation requests、logout 和 audit-log reads；不会记录 password、OAuth code、request body 或 API token。Admin 用户可以在 `/evaluations/security` 查看最近事件。本地前后端分开运行时，如果希望安全页面包含后端事件，需要把两边的 `SECURITY_AUDIT_LOG_PATH` 设置成同一个绝对路径。

从示例创建 `scripts/eval_cases.json`：

```bash
cp scripts/eval_cases.example.json scripts/eval_cases.json
```

运行 retrieval evaluation：

```bash
python3 scripts/evaluate_retrieval.py --base-url http://localhost:8000 --cases scripts/eval_cases.json
```

运行 fix evaluation：

```bash
python3 scripts/evaluate_fix.py --base-url http://localhost:8000 --cases scripts/eval_cases.json
```

核心指标：

- Retrieval: Recall@5 和平均延迟
- Fix: Fix Success Rate、平均 tool calls、平均延迟

## 校验命令

Backend:

```bash
python3 -m compileall backend/app
cd backend
./.venv/bin/python -c "from app.main import app; print(app.title)"
```

Frontend:

```bash
cd frontend
npm install --cache .npm-cache
npm run lint
npm run typecheck
npm run build
```

Compose config:

```bash
docker compose config
```

## 当前能力

- Git URL 仓库索引
- TS/JS/Python/Vue SFC 文件扫描
- 函数、类、方法、箭头函数和基础 React 组件的 AST 语义 chunk
- Vue SFC template、script、script setup chunk
- PostgreSQL 元数据存储
- Qdrant 向量存储
- Hybrid retrieval
- 多仓库 retrieval 和带 repo 级 citation 的 SSE Q&A
- Repo Memory 持久化，包含语言、模块、依赖、关键文件和符号摘要
- CI inspection 和 GitHub Actions workflow 写入
- 带 citation 的 SSE code chat
- LangGraph bug-fix Agent
- 基于文件内容 hash 的增量 reindex
- PR Review API 和 UI，包含结构化 findings 和 citations
- Docker sandbox 测试验证
- gVisor Docker runtime 和 Firecracker external runner 沙箱选项
- Real-time Agent Timeline
- Diff Viewer
- Run feedback API
- OpenAI、DeepSeek 和自定义 endpoint 的 OpenAI-compatible LLM provider
- 带向量维度校验的 OpenAI-compatible embedding provider
- 结构化代码 embedding 文本、确定性 rerank、same-file context expansion
- Evaluation Center，包含 datasets、snapshots、runs、artifacts、history、compare reports、CI gates
- 前后端 Evaluation RBAC，支持 GitHub OAuth、viewer/admin roles 和 scoped service tokens
- Signed proxy identity headers，支持 HMAC verification、nonce replay protection、Redis nonce storage、current/previous key rotation
- 记录前后端 Evaluation 行为和 resolved principal 的安全审计日志

## 简历表述

```text
CodeMate: 代码库问答与自动修复 Agent
技术栈: Next.js 14, FastAPI, LangGraph, PostgreSQL, Qdrant, Redis/RQ, Docker

- 设计并实现 TypeScript/JavaScript/Python 仓库 AST 语义索引流水线，将 chunk 元数据存入 PostgreSQL，将向量存入 Qdrant，用于带文件/行号引用的代码问答。
- 实现关键词检索、向量检索、repo metadata filter、确定性 rerank 和 same-file context expansion 结合的 hybrid retrieval，降低模型伪造 citation 的概率。
- 基于 LangGraph 设计代码修复 Agent，包含 parse、retrieve、read、diagnose、patch、test、reflect、final 节点，并实现 bounded retry。
- 将 Agent 生成补丁放入 Docker 沙箱验证，支持命令白名单、timeout、资源限制和禁网测试执行。
- 建设 Evaluation Center，支持 retrieval/fix 数据集、快照、运行产物、历史对比和 CI gate 集成。
- 加固 Evaluation API，支持后端 RBAC、signed proxy identity header、replay nonce protection、scoped service token、key rotation 和 principal-aware audit log。
- 基于 SSE 构建 Next.js Agent Timeline，展示 plan、tool calls、patch diff、test result、reflection 和 final summary，不暴露隐藏模型推理。
```

## 后续工作

- 接入 learned rerank provider，并扩展更多语言 parser
- 提供托管 Firecracker runner，用于更强多租户隔离
- 增加定时 evaluation regression report
