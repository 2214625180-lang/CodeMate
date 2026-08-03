# Capability Matrix and Evidence Status

**Status date:** 2026-08-03. This document is the source of truth for what CodeMate claims today. A checked-in implementation, a local test, a CI workflow definition, and a successful staging exercise are different kinds of evidence.

| Capability | Implemented | Locally verified | CI verified | Staging verified | Planned / not claimed | Evidence and boundary |
| --- | --- | --- | --- | --- | --- | --- |
| Controlled repair loop and strict `verified_success` verdict | Yes | Yes | Workflow defined; no checked-in remote run receipt | No | Real-model benchmark rates | Source and tests under `backend/app/agent/` and `backend/tests/test_agent_*.py`; a result counts only when baseline, target, and regression evidence exists. |
| Retrieval benchmark fixture and hybrid retrieval smoke result | Yes | Yes | Evaluation gate is defined; no checked-in CI receipt | No | Real-model retrieval/fix benchmark matrix | [Local artifact](../benchmarks/results/local-retrieval-latest.json) is explicitly `engineering_smoke_only`, uses mock embeddings, and must not be generalized to model quality. |
| Product API user isolation | Yes | Yes | Production-readiness workflow is defined; no checked-in remote run receipt | No | Multi-tenant SaaS | Signed product identities scope `/repos` and `/runs` by `owner_id`. Local mode is intentionally one user, `local:local-dev`. |
| Docker test sandbox | Yes | Yes | Container policy job is defined; no checked-in remote run receipt | No | A production Docker-socket topology | The local **demo overlay only** mounts the Docker socket into the worker to start network-disabled test containers. That convenience is not production evidence. |
| Managed execution-plane protocol, policy checks, manifests, and qualification scripts | Yes, as control-path code and deployment artifacts | Unit/integration simulation only | Supply-chain and qualification workflow definitions are present; no checked-in successful staging artifact | No | A deployed HA execution plane | See [managed execution plane](managed-sandbox-execution-plane.md). Configuration guards and manifests are not proof that Firecracker, Kata, HA Redis, Cosign, or TEE controls ran in an environment. |
| Firecracker runtime | Partial: client/control-path and service-unit artifacts | No runtime evidence | No runtime evidence | No | Run a signed rootfs on real KVM nodes and retain qualification evidence | Do not claim Firecracker execution is implemented end-to-end until a signed release artifact records it. |
| Kubernetes/Kata runtime | Partial: Kubernetes/Kata manifests and request contract | No runtime evidence | No runtime evidence | No | Apply the manifests to a Kata-enabled cluster and retain qualification evidence | A `RuntimeClass/kata` reference in a manifest is not an executed Kata workload. |
| Staging qualification, KMS/SIEM/HA fault drills | Script, policies, and evidence format implemented | Rehearsal only can be run locally | Manual workflow definition exists | **No `qualified` artifact committed** | Execute a real protected staging run | Only a signed manifest with `qualification.json: decision=qualified` can change this cell to “Yes”. |

## Evidence rules

- **Implemented** means source code, migration, manifest, or script is checked in and has a focused automated test when the behavior is testable. It does not mean deployed.
- **Locally verified** means a developer has run a reproducible command against local code. It is not a claim about external infrastructure.
- **CI verified** requires a successful immutable CI run URL or exported receipt linked from a release/PR artifact. A YAML workflow alone is not enough.
- **Staging verified** requires a dated staging evidence bundle, its manifest hash/signature, environment identifier, commit SHA, and an explicit successful decision. Mock and rehearsal evidence remain local only.
- **Planned** includes runtime and operational claims whose code or manifests exist but lack the evidence required above. It is intentionally visible rather than implied.

## Version sources

`frontend/package.json` is the runtime source of truth for the frontend: **Next.js 15.5.22**, React 18.3.1, and TypeScript 5.5.3. Product documents should cite the manifest or lockfile rather than manually copied version strings.

## History and iteration policy

The initial repository history includes a bulk baseline import. It is retained as historical fact: this project does not rewrite commits, split past commits after the fact, or invent prior PRs/results.

From this point forward, each substantive change should have:

1. a GitHub issue that states the problem, acceptance criteria, and risk;
2. one focused branch/PR with Conventional Commit(s) and a linked issue;
3. command output or uploaded CI artifacts for every claimed verification level;
4. an ADR for material architectural/security decisions; and
5. a release or benchmark artifact for any published metric or staging claim.

Use the repository [PR template](../.github/PULL_REQUEST_TEMPLATE.md) and [evidence ADR](adr/0006-evidence-backed-capability-claims.md). They are process guardrails, not retroactive proof for earlier commits.
