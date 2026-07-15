# ADR 0001: Durable MCP execution before remote side effects

Status: Accepted

## Decision

Create and claim a durable execution row before calling a remote MCP Tool. Each logical call has a unique idempotency key, a lease and an explicit terminal or `unknown` state.

## Rationale

Network failure after sending a request cannot prove whether the remote side effect happened. Blind retries are unsafe. An `unknown` state plus reconciliation preserves ambiguity instead of inventing success or failure.

## Consequences

- Recovery is more complex than retry loops.
- Remote retry is allowed only when the Server declares a metadata idempotency contract.
- Human reconciliation becomes part of the operational model.
