# CURRENT-MARKETS-001A final adversarial self-review

## P0 review

- Wrong FPL/Odds fixture join: **closed** by exact 001B mapping selection, dual-namespace DAT-003
  canonical convergence, complete identity-view set equality and multi-fixture tests.
- Post-cutoff Odds accepted: **closed** by decision-information `as_of`, Stage-6 freshness and
  explicit future/stale totals gates. Blocked fixtures publish no usable constraints.
- Provider orientation reversed: **closed** by accepted 001B exact home/away/kickoff reconstruction
  plus provider-native canonical HOME/DRAW/AWAY input use.
- Restricted derived state persisted: **closed** by pure construction, denied storage rights,
  offline tests, real PostgreSQL before/after counts and zero product DB writes.
- Fake Stage-7 provenance: **closed**; no minutes context or score service call exists.

Unresolved P0: **0**.

## P1 review

- Raw Odds prices not bound: **closed**; price mutations change Odds market, 001D, consensus,
  fixture and bundle semantic hashes, while stale requests fail.
- H2H vig not removed: **closed** by unchanged accepted Stage-6 power normalisation and tests.
- Totals vig not removed: **closed** by exact binary power normalisation with proportional
  sensitivity and exact complement tests.
- Duplicate bookmaker weighting: **closed** by canonical-operator alias collapse for both families;
  tied conflicts quality-block rather than select arbitrarily.
- Missing source/provenance binding: **closed** by exact request and lineage fields.
- Unsupported totals silently rounded: **closed**; exact half-goal validation rejects quarter lines.
- Canonical IDs invented: **closed**; product canonical IDs come only from exact accepted SELECTs.
  Adapter-local UUIDv5 identities are explicitly transient and noncanonical.
- Full GCS-008 called with fake minutes: **closed**; output stops at `MarketConstraintSet`.

Unresolved P1: **0**.

## Material P2 review

- Target deadline used as cutoff: **closed**; market `as_of` is latest source/resolution readiness,
  while the accepted 001D cutoff remains a separate lineage/output field.
- Extra provider events rejected: **closed**; unrelated events are ignored and tested.
- Ordering changes identity: **closed** for event, bookmaker, outcome and identity-view order where
  accepted source semantics declare order nonmaterial.
- Summary/error leaks: **closed** across public summary, message, details object, `str` and `repr`.
- H2H-only described ready: **closed** by explicit three-state invariants and affected-fixture test.
- Score prior silently invented: **closed** by exact `NO_ACCEPTED_CURRENT_SCORE_PRIOR` limitation.

Unresolved material P2: **0**.

## P3 review

No unresolved P3 finding remains. Defensive validators not reached by structurally valid accepted
inputs were inspected manually in addition to the 92.3154701718908% branch-aware numerical gate.

## Scope review

No accepted Stage-6 or GCS-008 source was weakened. No predecessor migration, policy, current
source compiler, acquisition path, CLI, orchestration or optimiser was changed. No dependency was
added. No PR, merge, production activation or human-acceptance claim is part of this branch.

Final same-agent verdict:

`CURRENT_MARKETS_001A_IMPLEMENTED_PENDING_INDEPENDENT_REVIEW`
