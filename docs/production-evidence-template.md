# CodeMate Production Evidence Report

## Build

- Commit:
- Environment:
- Date:
- Operator:

## Release gates

| Gate | Result | Artifact |
|---|---|---|
| Backend unit/API tests |  |  |
| Frontend production build |  |  |
| Alembic upgrade/check/downgrade |  |  |
| PostgreSQL + Redis + MCP + OAuth E2E |  |  |
| Dependency security audit |  |  |
| AWS KMS round-trip and credential rewrap |  |  |
| SIEM signed delivery receipt |  |  |
| S3 Object Lock receipt/version |  |  |
| Sandbox HA idempotency/fencing |  |  |
| Sandbox Cosign/SLSA/rootfs negative controls |  |  |
| Sandbox TPM/TEE negative control |  |  |
| Sandbox evidence manifest signature |  |  |

## Performance

| Metric | Target | Actual |
|---|---:|---:|
| Throughput |  |  |
| P50 |  |  |
| P95 |  |  |
| P99 |  |  |
| Success rate |  |  |
| Quota accounting accuracy | 100% |  |

## Recovery drills

| Scenario | Expected | Observed | Recovery time |
|---|---|---|---:|
| Redis restart | Fail closed; reconcile after recovery |  |  |
| PostgreSQL restart | No unsafe remote retry |  |  |
| Worker crash | Lease expiry and safe resume/reconciliation |  |  |
| MCP timeout after send | Execution becomes unknown |  |  |
| Execution-plane Pod deletion | Requests continue through healthy replicas |  |  |
| Sandbox Redis primary failover | Shared replay/idempotency state remains safe |  |  |
| Sandbox scale-out/scale-in | Minimum HA capacity remains ready |  |  |
| Sandbox mTLS leaf rotation | Secret and Pods rotate without unauthorized access |  |  |

## Security evidence

- Cross-Tenant authorization test:
- Delegated OAuth PKCE test:
- Secret redaction/encryption test:
- Audit log sample:
- Open risks and accepted exceptions:
- Security audit outbox pending/dead-letter count:
- Evidence manifest SHA-256 verification:

## Decision

- Release / Hold:
- Approver:
- Follow-up actions:
