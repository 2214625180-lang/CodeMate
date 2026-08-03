# ADR 0006: Evidence-backed capability claims

- **Status:** Accepted
- **Date:** 2026-08-03

## Context

CodeMate contains local product code, CI definitions, deployment manifests, and staging-qualification automation. Treating all four as equivalent evidence makes the project difficult to assess and encourages claims that cannot be reproduced from the repository. The existing history also contains an initial bulk baseline import; rewriting it would conceal rather than improve that fact.

## Decision

Use the five evidence levels in [Capability Matrix](../capability-matrix.md): Implemented, Locally verified, CI verified, Staging verified, and Planned. Documentation must name the level for managed-runtime, security, benchmark, and deployment claims.

New substantive work must link an issue, a focused PR, its verification commands/artifacts, and an ADR when it changes an architecture or security boundary. Published benchmark and staging results must include the commit SHA, dataset/config snapshot, environment identifier, timestamps, and immutable artifact hash or signature.

## Consequences

- Existing history remains unchanged and no earlier evidence is fabricated.
- A workflow file, mock test, or manifest may support an **Implemented** claim but cannot by itself support **CI verified** or **Staging verified**.
- Firecracker/Kata, HA Redis, KMS/SIEM, and real-model metrics remain visible as partial or planned until evidence meets the required level.
- The process creates smaller, independently reviewable changes going forward, at the cost of maintaining issue/PR and artifact links.
