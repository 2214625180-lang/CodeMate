# ADR 0005: Durable dual-sink security audit export

Status: Accepted

## Context

Local JSONL and CI artifacts are neither durable delivery queues nor immutable evidence. Direct synchronous SIEM calls couple management API availability to a remote vendor.

## Decision

Persist a fail-closed request intent before security-sensitive handlers and a correlated completion event afterward. Create one leased outbox delivery per HTTP SIEM and S3 sink. Use HMAC, payload hashes, idempotency keys, bounded retries, dead-letter visibility and S3 COMPLIANCE Object Lock.

## Consequences

PostgreSQL availability is required for management actions. SIEM/S3 outages do not lose accepted evidence but grow the retry backlog and eventually make readiness fail. Delivered local receipts are retained for 90 days; remote immutable retention is longer.
