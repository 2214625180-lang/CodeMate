# CodeMate

CodeMate is a small but complete code repository Q&A and bug-fixing Agent. It indexes TypeScript, JavaScript, and Python repositories into semantic AST chunks, answers questions with file and line citations, and runs a LangGraph repair workflow that generates a patch and validates it in a Docker sandbox.

## Architecture

```text
Frontend: Next.js 14 + TypeScript + TailwindCSS
  - Repository list/detail
  - Code chat with citations
  - Bug fix page
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
  - PostgreSQL: repository, files, chunks, runs, steps, evaluations
  - Qdrant: chunk embeddings and payload metadata
  - Redis/RQ: background indexing and agent jobs
  - Docker: local services and sandbox test runner
```

## Tech Stack

- Frontend: Next.js 14, TypeScript, TailwindCSS
- Backend: FastAPI, Python 3.11, SQLAlchemy
- Agent: LangGraph
- Queue: Redis + RQ
- Database: PostgreSQL
- Vector DB: Qdrant
- Sandbox: Docker CLI through the worker container
- Providers: Mock by default; OpenAI-compatible LLM and embedding providers are supported

## Local Start

```bash
cp .env.example .env
docker compose up --build
```

Open:

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health
- Qdrant: http://localhost:6333

If Docker Hub pulls fail with `auth.docker.io ... timeout`, retry after network access is stable or pre-pull the base images:

```bash
docker pull python:3.11-slim
docker pull node:20-alpine
docker pull postgres:16-alpine
docker pull redis:7-alpine
docker pull qdrant/qdrant:v1.9.5
```

## Provider Configuration

The default `.env.example` keeps `LLM_PROVIDER=mock` and `EMBEDDING_PROVIDER=mock`, so local startup does not require API keys.

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

Custom OpenAI-compatible endpoint:

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

`EMBEDDING_DIMENSION` must match the embedding vector size returned by the model. For `text-embedding-3-*` models, CodeMate sends the configured dimension to the API; for other embedding models, update this value to the provider's returned vector size.

When changing `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, or `EMBEDDING_DIMENSION`, re-index affected repositories so Qdrant is rebuilt with vectors from the new model. CodeMate embeds structured code text containing file path, language, symbol metadata, imports, exports, and chunk content.

Retrieval tuning:

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

The retrieval flow now performs hybrid keyword/vector recall, deterministic rerank, and same-file context expansion. Expansion adds parent/sibling chunks around high-confidence matches while preserving exact citation ranges.

Repository memory and CI generation:

```env
REPO_MEMORY_MAX_FILES=12
REPO_MEMORY_MAX_SYMBOLS=30
CI_WORKFLOW_FILENAME=codemate-ci.yml
```

Repo Memory is refreshed after successful indexing and can also be refreshed manually. CI inspection detects common local CI configs and generates a GitHub Actions workflow for Node and Python projects.

## Demo Repository

Create a small JavaScript repo:

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

Commit it and expose it as a Git URL the backend can clone.

## Repository Indexing

```bash
curl -X POST http://localhost:8000/repos \
  -H "Content-Type: application/json" \
  -d '{"repo_url":"https://github.com/your-user/demo-bug-repo.git"}'
```

Check status:

```bash
curl http://localhost:8000/repos/<repo_id>/status
```

Expected flow:

```text
pending -> cloning -> parsing -> embedding -> indexed
```

Reindexing an existing repository is incremental by default. CodeMate updates the workspace, compares indexed file hashes with the current checkout, deletes vectors for removed or changed files, and embeds only new or changed chunks. Force a full rebuild when needed:

```bash
curl -X POST "http://localhost:8000/repos/<repo_id>/reindex?full=true"
```

Read or refresh Repo Memory:

```bash
curl http://localhost:8000/repos/<repo_id>/memory

curl -X POST http://localhost:8000/repos/<repo_id>/memory/refresh
```

Inspect or write CI workflow:

```bash
curl http://localhost:8000/repos/<repo_id>/ci

curl -X POST http://localhost:8000/repos/<repo_id>/ci/workflow
```

Inspect Qdrant:

```bash
curl http://localhost:6333/collections/codemate_chunks

curl -X POST http://localhost:6333/collections/codemate_chunks/points/scroll \
  -H "Content-Type: application/json" \
  -d '{"limit":3,"with_payload":true,"with_vector":false}'
```

## Code Q&A

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

Multi-repository Q&A:

```text
/repos/chat
```

```bash
curl -N -X POST http://localhost:8000/repos/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"认证逻辑在哪些仓库里？","repo_ids":["repo-a","repo-b"]}'
```

If `repo_ids` is omitted, CodeMate searches indexed repositories up to `MULTI_REPO_MAX_REPOS`. Multi-repo citations include `repo_id` and `repo_name`, so snippets can be opened from the correct workspace.

The SSE stream emits:

```text
token
citation
done
error
```

If retrieval finds nothing, the system returns:

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

Poll run result:

```bash
curl http://localhost:8000/runs/<run_id>
```

Stream trace:

```bash
curl -N http://localhost:8000/runs/<run_id>/trace
```

Submit feedback:

```bash
curl -X POST http://localhost:8000/runs/<run_id>/feedback \
  -H "Content-Type: application/json" \
  -d '{"status":"accepted"}'
```

Trace events:

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

The frontend Timeline shows only explainable events, not hidden model chain-of-thought.

## PR Review

Frontend:

```text
/repos/<repo_id>/review
```

Review a pasted diff:

```bash
curl -X POST http://localhost:8000/repos/<repo_id>/review \
  -H "Content-Type: application/json" \
  -d '{"diff":"diff --git a/src/app.ts b/src/app.ts\n...","question":"Focus on correctness and tests"}'
```

Review refs from the indexed workspace:

```bash
curl -X POST http://localhost:8000/repos/<repo_id>/review \
  -H "Content-Type: application/json" \
  -d '{"base_ref":"origin/main","head_ref":"origin/feature"}'
```

The response contains a summary, changed files, structured findings, and citations from retrieved repository context.

## Sandbox Notes

- Temporary workspaces are created under `SANDBOX_WORKSPACE_DIR`.
- `.env*`, `node_modules`, build output, and coverage folders are excluded.
- Patches are applied with `git apply`.
- Test commands must be listed in `SANDBOX_ALLOWED_COMMANDS`.
- Docker tests run with CPU, memory, timeout limits, and `--network none` by default.
- `SANDBOX_RUNTIME=docker` uses the standard Docker runtime.
- `SANDBOX_RUNTIME=gvisor` adds `--runtime ${SANDBOX_GVISOR_DOCKER_RUNTIME}` to Docker, defaulting to `runsc`.
- `SANDBOX_RUNTIME=firecracker` executes `SANDBOX_FIRECRACKER_COMMAND_TEMPLATE`, an external Firecracker runner command with `{workspace}`, `{image}`, `{command}`, and `{timeout}` placeholders.
- The worker mounts `/var/run/docker.sock` so it can start sandbox containers.
- With Docker Compose, `backend/sandbox-runs` is mounted at the same absolute path on host and worker because Docker bind mounts are resolved by the Docker daemon.

## Evaluation

Create `scripts/eval_cases.json` from the example:

```bash
cp scripts/eval_cases.example.json scripts/eval_cases.json
```

Run retrieval evaluation:

```bash
python3 scripts/evaluate_retrieval.py --base-url http://localhost:8000 --cases scripts/eval_cases.json
```

Run fix evaluation:

```bash
python3 scripts/evaluate_fix.py --base-url http://localhost:8000 --cases scripts/eval_cases.json
```

Metrics:

- Retrieval: Recall@5 and average latency
- Fix: Fix Success Rate, average tool calls, average latency

## Validation Commands

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

## Current Capability

- Git URL repository indexing
- TS/JS/Python/Vue SFC file scanning
- AST semantic chunks for functions, classes, methods, arrow functions, and basic React components
- Vue SFC chunks for template, script, and script setup blocks
- PostgreSQL metadata storage
- Qdrant vector storage
- Hybrid retrieval
- Multi-repository retrieval and SSE Q&A with repo-scoped citations
- Persisted Repo Memory with language, module, dependency, key file, and symbol summaries
- CI inspection plus generated GitHub Actions workflow writing
- SSE code chat with citations
- LangGraph bug-fix Agent
- Incremental repository reindexing by file content hash
- PR Review API and UI with structured findings and citations
- Docker sandbox test validation
- gVisor Docker runtime and Firecracker external runner sandbox options
- Real-time Agent Timeline
- Diff Viewer
- Run feedback API
- Real OpenAI-compatible LLM provider for OpenAI, DeepSeek, and custom endpoints
- Real OpenAI-compatible embedding provider with vector dimension validation
- Structured code embedding text, deterministic rerank, and same-file context expansion
- Basic evaluation scripts

## Resume Wording

```text
CodeMate: Code Repository Q&A and Bug-Fixing Agent
Tech stack: Next.js 14, FastAPI, LangGraph, PostgreSQL, Qdrant, Redis/RQ, Docker

- Built an AST-based indexing pipeline for TypeScript/JavaScript/Python repositories, storing chunk metadata in PostgreSQL and embeddings in Qdrant for citation-grounded code Q&A.
- Implemented hybrid retrieval combining keyword search, vector search, repo metadata filters, and deterministic citation handling to avoid fabricated file paths and line numbers.
- Designed a LangGraph repair Agent with parse, retrieve, read, diagnose, patch, test, reflect, and final nodes, including bounded retry logic.
- Isolated generated patches in a Docker sandbox with command allowlists, timeouts, resource limits, and network-disabled test execution.
- Built a Next.js Agent Timeline over SSE that displays plan, tool calls, patch diff, test result, reflection, and final summary without exposing hidden model reasoning.
```

## Later P1/P2 Extensions

- Claude provider
- External learned rerank provider
