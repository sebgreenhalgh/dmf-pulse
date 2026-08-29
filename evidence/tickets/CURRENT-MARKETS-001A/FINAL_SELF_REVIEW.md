# CURRENT-MARKETS-001A third-remediation engineering self-review

## Reproduced final-review findings

- CMR-IR-010: at the reviewed starting head, post-receipt H2H evidence reached `continue` before
  HOME/AWAY/DRAW provider-label validation. The guard now precedes temporal exclusion. Freshly
  rehashed corrupt future labels block for every outcome, alias cardinality, timestamp source and
  ordering; valid future aliases still exclude and valid older aliases remain.
- CMR-IR-011: at the reviewed starting head, reversing valid multi-line `totals_markets` changed
  the LIVE-ODDS semantic hash and downstream identities. Exact-Decimal line sorting is now limited
  to the semantic projection. Two-/three-line and nested ordering permutations are invariant;
  line-set and price changes remain material.

## Preserved regressions and boundaries

CMR-IR-002/003/004/005/006/007/009 remain independently closed. CMR-IR-001 local label behavior
and CMR-IR-008 authoritative cross-source reconstruction are engineering-restored through the
CMR-IR-010 regression. Temporal/rights/quality/source/request digests, operator occurrence
applicability, HUMAN_VERIFIED authority, official-FPL scope and disclosure remain exact.

The upstream change does not alter stored tuple order, the normal LIVE-ODDS builder, preferred
totals selection, schemas/versions, H2H ordering, Decimal representation, prices, Stage-6
normalization, rights, temporal, quota, identity, acquisition, database or persistence. The
normal builder semantic hash is unchanged at
`27880ba63a4555ee74f21b8c5acdeccc73c7194d57b8ea663bef8fed4cc44abf`.

## Coverage, package and runtime

The exact focused selector passed 122 tests. Raw current-module statement coverage is 818/841
(97.26516052318668%); raw branch coverage is 230/248 (92.74193548387096%). These are separate
figures and both exceed 90%. Inherited populations passed 372 source-state, 173 markets, 209
GCS-008, 50 PostgreSQL markets and 90 DAT-003 PostgreSQL/migration tests.

All four installed-wheel gates passed outside the source tree. CURRENT-MARKETS blocked corrupt
future HOME/AWAY/DRAW, retained valid older H2H, excluded post-receipt evidence, proved complete
totals order identity and made zero network requests. The package remains `dmf-pulse==0.2.0`.

## Adversarial conclusion

- New P0 found/unresolved: 0 / 0.
- New P1 found/unresolved: 0 / 0.
- New material P2 found/unresolved: 0 / 0.
- New P3 found/unresolved: 0 / 0.

CMR-IR-010/011 are engineering-closed at
`316d52b87f113f9364ee0dab9c296cf8fe0ff544`. This is not independent confirmation.

`CURRENT_MARKETS_001A_REMEDIATED_PENDING_INDEPENDENT_REREVIEW`
