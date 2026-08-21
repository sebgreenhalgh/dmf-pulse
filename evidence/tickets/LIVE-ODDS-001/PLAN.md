# LIVE-ODDS-001 plan and preflight

Status: `IN_PROGRESS` / engineering implementation only.

## Immutable Git boundary

- Parent and fetched `origin/main`: `baed47bce7a158d91afe38351a2c65be60444adf`.
- Readiness donor: `d4cc759d4600489c21ba738cfc9b357cc380554e`.
- Verified merge base: `9eb57143f6ee92f67c78607cc386678d962e62d4`.
- Isolated branch: `integration/post-gw1/LIVE-ODDS-001-production-live-odds`.
- Existing readiness and candidate worktrees were inspected read-only and remain untouched.

## Authority resolution

The authority manifest maps the provider foundation to A5 and downstream market exclusion to A6.
The controlling decisions are ADR-GOV-001/002/004, ADR-RES-001, ADR-DATA-001/003/004/007,
ADR-SRC-001/002/003/004, ADR-MKT-001..006, ADR-ASSUR-006, and ADR-IMPL-001/003.

The current official provider documentation was checked on 2026-08-21 without making an API call.
It confirms the approved HTTPS host, `h2h`/`totals`, automatic additive families such as `h2h_lay`,
and quota headers/cost. The current public terms remain compatible with private analytical use and
still prohibit standalone redistribution. They do not resolve raw-retention, backup, or training
rights, so the repository's governed `UNKNOWN -> DENY` decisions remain unchanged.

## Checkpoint sequence

1. Freeze RED provider-drift, transport, security, rights, temporal, and provenance contracts.
2. Port the narrow credential boundary and implement the explicit stdlib transport against main.
3. Port/rewrite the provider-native current adapter with additive drift warning/exclusion.
4. Run full pre-review hardening, produce final evidence, commit, push, and verify remote equality.

No live smoke, real credential, identity reconciliation, consensus algorithm change, migration,
PR, merge, tag, or acceptance claim is authorised.
