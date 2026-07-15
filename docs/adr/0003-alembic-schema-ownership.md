# ADR 0003: Alembic owns the production schema

Status: Accepted

## Decision

Normal application startup runs Alembic migrations. It does not use `Base.metadata.create_all` or ad-hoc column bridges.

## Rationale

Production changes require reviewable revisions, deterministic upgrade order, drift detection and rollback exercises.

## Consequences

- Unversioned legacy databases are rejected by default.
- Legacy adoption is an explicit, backup-gated one-time command.
- Every ORM schema change must include a migration revision and pass `alembic check`.
