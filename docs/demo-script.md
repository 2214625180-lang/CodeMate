# CodeMate Interview Demo

The main demo uses a real LLM and the built-in multi-file fixture in `examples/demo-cart-bug`. The deterministic Mock provider remains available for unit and smoke tests, but the demo launcher refuses to run when `LLM_PROVIDER=mock`.

## 1. Configure a real planner and patch model

Copy the normal environment file and configure one supported real provider:

```bash
cp .env.example .env
```

Minimal OpenAI-compatible example:

```env
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=https://your-provider.example/v1
LLM_MODEL=your-chat-model
LLM_API_KEY=replace-me
```

`LLM_MODEL` must be explicit. `make demo` validates the provider, model, credential, Docker daemon, and local Docker socket before starting anything. `EMBEDDING_PROVIDER=mock` is allowed for a cheap deterministic local index; only retrieval embeddings remain Mock in that configuration—the planner and patch generator are still the configured real model.

If a default host port is occupied, change the corresponding `.env` value before launching, for example:

```env
POSTGRES_PORT=15432
REDIS_PORT=16379
QDRANT_HTTP_PORT=16333
QDRANT_GRPC_PORT=16334
BACKEND_PORT=18000
FRONTEND_PORT=13000
```

The frontend build-time API URL, health probe, CORS origin, and printed links all follow these values.

## 2. Start, import, index, seed the benchmark, and run

```bash
make demo
```

The command performs the full setup:

1. starts PostgreSQL, Redis, Qdrant, backend, worker, and frontend;
2. creates a deterministic Git commit from `examples/demo-cart-bug`;
3. imports and fully indexes that repository without an external Git host;
4. creates or updates the `Interview Demo - Multi-file Cart Fix` benchmark dataset;
5. creates and enqueues a fix run using `npm run test:targeted`;
6. prints clickable repository, live Agent Timeline, and benchmark URLs.

The local demo Compose overlay mounts the Docker socket only into the worker so it can launch network-disabled test containers. This is a local presentation convenience, not a production deployment topology; production uses the managed sandbox execution plane.

To seed without spending model tokens, run:

```bash
make demo-seed
```

To stop the local stack without deleting database or index volumes:

```bash
make demo-down
```

## 3. Why this is not a Mock happy path

The fixture contains three related production modules:

- `src/cart.js` applies a fixed-value coupon but initially allows a negative discounted subtotal;
- `src/checkout.js` initially calculates tax from the pre-discount subtotal;
- `src/tax.js` owns tax validation and rounding.

The failure is reproducible before any patch:

```bash
cd examples/demo-cart-bug
npm run test:targeted
npm test
```

Both commands must fail on the fixture commit. There are no runtime dependencies, so the sandbox can keep networking disabled and still execute the tests.

The test split creates a genuine reflection opportunity:

- the targeted test exposes the coupon floor defect;
- the full regression suite exposes the cross-file tax-base invariant;
- a narrow first patch can pass the target and fail regression, causing the controlled loop to reset the workspace, retain the new evidence, gather more context, and try a combined patch.

No code forces “iteration one must fail.” A model that diagnoses both root causes immediately may reach verified success in one patch; that is a legitimate stronger result.

## 4. Present the Timeline

Open the `Agent timeline` URL printed by `make demo`. The `runId` query parameter reconnects the UI to the already-enqueued run and replays persisted events.

Walk through:

- `inspection`: repository metadata plus targeted and detected regression commands;
- `baseline_test_result`: the pre-patch targeted test ran and failed;
- `agent_plan`: a schema-validated `PlanNextAction` and remaining budgets;
- `tool_call` / `tool_result`: the observation-dependent Search, Read, Symbol, Reference, or Test path chosen by the real model;
- `patch`: the proposed unified diff and its fingerprint;
- `targeted_test_result`: the target test after patch application;
- `regression_test_result`: the detected full `npm test` suite;
- `reflection`: only when apply, target, or regression evidence requires another iteration;
- `verification`: the strict terminal status and baseline/target/regression evidence;
- `final`: summary, diff, model/tool usage, and feedback controls.

State clearly that the Timeline contains observable decisions and evidence, not hidden chain-of-thought.

## 5. Success criteria

Only call the run successful when the UI shows `verified_success`. That requires:

- the pre-patch targeted test ran and failed;
- the post-patch targeted test ran with exit code 0;
- the full regression test ran with exit code 0.

`unverified_patch`, `not_reproduced`, `failed`, and `infra_error` are distinct outcomes and do not count toward Fix Success Rate.

The expected production changes are restricted to `src/cart.js` and `src/checkout.js`. Test edits do not satisfy the seeded benchmark case.

## 6. Show the benchmark record

Open the `Benchmark` URL printed by the launcher. The seeded dataset records:

- fixture commit SHA;
- LLM provider and explicit model;
- embedding provider and model;
- target and regression commands;
- expected terminal status `verified_success`;
- allowed changed files;
- the fact that no synthetic first-iteration failure is forced.

Run the dataset from Evaluation Center when you want a separately persisted evaluation artifact. Do not put invented success percentages in the README; use the produced artifact and recorded metadata.
