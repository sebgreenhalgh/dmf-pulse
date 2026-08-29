# CURRENT-MARKETS-001A third-remediation result

## Git and chronology

- Architectural parent: `4eda6fe9ba0db917ac09bf9a877b1a31c6c3f9fb`.
- Final independently reviewed starting head: `ee4a35760a56f84b4f0f50f3d2f898e2037d105a`.
- Third-remediation product/tests commit:
  `316d52b87f113f9364ee0dab9c296cf8fe0ff544`, a direct normal descendant of the reviewed head.
- Earlier deficient/remediation commits remain visible in unchanged ancestry.
- Work remained in the dedicated CURRENT-MARKETS worktree. The unrelated dirty
  CURRENT-AVAILABILITY worktree was not modified.

## CMR-IR-010 and CMR-IR-011

- CMR-IR-010: every supplied H2H HOME/AWAY/DRAW provider label is now checked against the
  already reconstructed event orientation before timestamp derivation, receipt exclusion and
  alias ranking. Malformed future evidence fails as disclosure-safe `SOURCE_INVALID`; valid
  future evidence remains normally excluded and a valid older alias remains usable.
- CMR-IR-011: under the explicit narrow authority, only the LIVE-ODDS supported-market semantic
  projection sorts `totals_markets` by exact Decimal line. The stored tuple and all builder,
  schema/version, selection, price, normalization, rights, temporal, quota, identity and
  persistence behavior remain unchanged.
- The ordinary live builder semantic hash stayed byte-identical before/after at
  `27880ba63a4555ee74f21b8c5acdeccc73c7194d57b8ea663bef8fed4cc44abf`.

Both findings are engineering-closed at `316d52b87f113f9364ee0dab9c296cf8fe0ff544`.
CMR-IR-001/008 are engineering-restored through the same regression. No fresh independent
closure is claimed.

## Verification

- Focused CURRENT-MARKETS selector: 122 passed.
- `src/dmf_pulse/markets/current.py`: 818/841 statements, 97.26516052318668%.
- Branches: 230/248, 92.74193548387096%.
- Combined branch-aware metric: 96.23507805325987%.
- Inherited FPL/LIVE-ODDS/001B/001D superset: 372 passed.
- Complete market unit/contract/golden/property population: 173 passed.
- GCS-008 regression population: 209 passed; no live service invocation.
- PostgreSQL market population: 50 passed, including 29 ticket-specific tests.
- DAT-003 PostgreSQL/migrations: 90 passed.
- Frozen sync, diff, Ruff, mypy, build, generic/ODD/GCS/CURRENT-MARKETS installed-wheel checks,
  canonical manifests, repository validation and secret scan pass.

The installed CURRENT-MARKETS wheel blocks malformed future HOME/AWAY/DRAW labels, proves
totals-line order invariance through source/request/result/summary, retains the valid older H2H
alias, excludes valid post-receipt evidence, verifies normal H2H/totals, and records zero network
calls.

## Preserved boundaries

CMR-IR-002/003/004/005/006/007/009 remain independently closed. The authoritative 001B/FPL
cross-source reconstruction, exact source binding, Stage-6 mathematics, GCS-008 Stage-7
requirement, rights, disclosure, database read-only behavior and zero persistence remain intact.

No availability source, score prior, goal rate, player allocation, Stage 9 or optimization was
changed or started. Stage-7 remains `DATA_BLOCKED`; the exact downstream blocker remains
`NO_ACCEPTED_CURRENT_SCORE_PRIOR`.

`CURRENT_MARKETS_001A_REMEDIATED_PENDING_INDEPENDENT_REREVIEW`

Next action: `INDEPENDENT_REREVIEW_CURRENT_MARKETS_001A`.
