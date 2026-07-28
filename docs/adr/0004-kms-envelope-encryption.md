# ADR 0004: Per-credential KMS envelope encryption

Status: Accepted

## Context

A single application master key makes database ciphertext recoverable after application-secret compromise and makes rotation operationally risky.

## Decision

Encrypt each credential with a unique AES-256-GCM data key. Wrap that key with AWS KMS using a fixed purpose context plus a hash binding the envelope to its owning database object. Store only the wrapped key and versioned envelope. Keep legacy decrypt support only for controlled rewrap migration.

## Consequences

Staging/production requires AWS KMS IAM availability. Database ciphertext swapping is rejected by owner binding. CMK migration invokes KMS once per credential and must be performed in an approved window.
