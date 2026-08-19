# GW1 Checkpoint 1.4C Hostile Identity Acceptance

## Scope

Bounded hostile review of the complete Checkpoint-1.4 team and target-Gameweek
fixture identity bridge after accepted capability commit
`291418d233745182f32e23395483aa88c367d1df` and evidence head
`ff57c0c12b8ba9f7730bf5d703c808e2b6f7955a`.

## Findings

- P0 — none.
- P1 — deserialized, correctly rehashed identity-map output did not independently
  reject every nested identity/context mutation. The service construction path was
  fail-closed, but the public output contract could accept contradictions in nested
  official identity, approval time, deadline, or reviewed team correspondence.
- P2 — none.
- P3 — none.

## Remediation

- Revalidate fixture, Gameweek, home-team and away-team provider/product/namespace/
  external-ID/season invariants.
- Revalidate exact provider-team to reviewed official-team correspondence.
- Revalidate mapping decision, team approval and fixture-binding approval cutoffs.
- Revalidate official deadline equality, target-season/Gameweek scope, coverage counts,
  used-team closure, source-lineage identity and semantic identity.
- Add adversarial mutations that recompute the public semantic hash, proving that
  structural validation—not stale-hash rejection alone—blocks contradictions.

## Local acceptance

- Exact identity tests — `59 passed`.
- Focused inherited suite — `165 passed, 1 deselected` on Windows; the deselected
  symlink test requires unavailable host privilege and remains active in Linux CI.
- Branch-aware identity coverage — `92.08%` (`431` statements, `150` branches).
- Ruff format — `PASS`.
- Ruff lint — `PASS`.
- Strict mypy — `PASS`.
- Wheel and sdist build — `PASS`.
- First-party secret scan — `PASS`, `finding_count=0`.
- Git diff check — `PASS`.
- PostgreSQL — `NOT_EXECUTED` because this identity bridge is deliberately transient
  and database-free.

## Safety state

- No fuzzy matching.
- No odds price influences fixture identity.
- No real provider credential was requested, read, logged, stored or used.
- No official-FPL-derived persistence was introduced.
- `REAL_CREDENTIALLED_PROVIDER_CALL = OPERATOR_CHECKPOINT`.
- Checkpoint 1.5 remains `NOT_STARTED` until this remediation is pushed and remotely
  validated.
