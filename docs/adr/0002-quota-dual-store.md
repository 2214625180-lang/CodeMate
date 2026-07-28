# ADR 0002: Redis coordination with PostgreSQL quota evidence

Status: Accepted

## Decision

Use Redis Lua for atomic low-latency rate/concurrency enforcement and PostgreSQL events/charges as durable accounting evidence.

## Rationale

PostgreSQL alone provides durable row locks but is inefficient for high-frequency counters. Redis alone loses durable auditability and can drift after failover. The dual-store design provides both properties.

## Consequences

- The stores are not one distributed transaction.
- A Tenant-scoped reconciliation lock temporarily denies new calls while repair rebuilds Redis from PostgreSQL.
- Production must fail closed when Redis is unavailable.
