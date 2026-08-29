# CURRENT-MARKETS-001A second remediation result

## Git and chronology

- Architectural parent: `4eda6fe9ba0db917ac09bf9a877b1a31c6c3f9fb`.
- Deficient reviewed implementation: `92f368597c22edbf77b236a8c96ddf959e545f59`.
- First substantive remediation: `30ad5c2e821eb03827e16f24d4b22a44ca3804a2`.
- Interrupted re-review unit: `f58790c4d2d3ed56a472bd3d52583451dbebab6c`.
- Second-remediation product/tests commit:
  `562e5a586881d9e462075ffd5dad01401b265ff3`, a direct normal descendant of `f58790c`.
- Work remained in the dedicated CURRENT-MARKETS worktree. The unrelated dirty
  CURRENT-AVAILABILITY worktree was not modified.

## Four current findings

- CMR-IR-003: H2H aliases now apply market or bookmaker-fallback receipt eligibility before
  canonical grouping and ranking. An invalid newer alias cannot suppress a valid older alias;
  all-future aliases contribute no H2H book.
- CMR-IR-007: the earlier reviewer-only autoflush probes are recorded as exploratory, not
  committed evidence. Two named committed PostgreSQL tests now retain pending/dirty ORM state
  with `autoflush=True`, observe no flush or DML, compare all relevant row counts, and roll back.
- CMR-IR-008: `build()` recomputes exact current event identity, reconstructs both accepted 001B
  team sides, and checks the current official-FPL fixture orientation/kickoff before any market
  use. A coherent participant-plus-label swap blocks; the local label guard remains independent.
- CMR-IR-009: operator occurrences are sorted unique target-only timestamps. One exact
  HUMAN_VERIFIED row must contain every occurrence; rows are never combined. A disclosure-safe
  occurrence digest makes stale or earliest-only applicability evidence fail reconstruction.

All four are `ENGINEERING_CLOSED_AT_562e5a586881d9e462075ffd5dad01401b265ff3`.
Fresh independent closure remains pending. CMR-IR-001/002/004/005/006 remain closed.

## Verification

- Focused CURRENT-MARKETS suite: 110 passed.
- `src/dmf_pulse/markets/current.py`: 818/841 statements, 97.26516052318668%.
- Branches: 230/248, 92.74193548387096%.
- Combined branch-aware metric: 96.23507805325987%.
- Inherited FPL/LIVE-ODDS/001B/001D superset: 368 passed.
- Complete market unit/contract/golden/property population: 161 passed.
- GCS-008 regression population: 209 passed; no live service invocation.
- PostgreSQL market population: 50 passed, including 29 ticket-specific tests.
- DAT-003 PostgreSQL/migrations: 90 passed.
- Frozen sync, diff, Ruff, mypy, build, generic/ODD/GCS/CURRENT-MARKETS installed-wheel checks,
  canonical manifests, repository validation, and secret scan pass.

The installed CURRENT-MARKETS wheel blocks coherent cross-source orientation, earliest-only
operator applicability, stale temporal and invalid rights attacks; retains the valid older H2H
alias; excludes post-receipt totals; verifies normal H2H/totals; and records zero network calls.

## Runtime, rights, disclosure and scope

Canonical resolution uses Core SELECTs only. PostgreSQL tests prove no autoflush, database write,
canonical creation, external mapping/operator creation, market consensus/current-market
persistence, or commit. Results remain PRIVATE and TRANSIENT_IN_MEMORY with storage, cache,
backup, display and redistribution denied. Safe summaries/errors expose no FPL fixture ID,
provider event/team, bookmaker key/title, price, or mapping internal.

No accepted predecessor, Stage-6 mathematics, GCS-008, schema/migration, availability source,
model, score prior, goal rate, player allocation, Stage 9 or optimisation was changed or started.
GCS-008 was not executed live. The exact downstream blocker remains
`NO_ACCEPTED_CURRENT_SCORE_PRIOR`.

`CURRENT_MARKETS_001A_REMEDIATED_PENDING_INDEPENDENT_REREVIEW`

Next action: `INDEPENDENT_REREVIEW_CURRENT_MARKETS_001A`.
