# PRIVATE-V1-ONE-COMMAND-001G command ledger

All product commands ran from the isolated `review_pack/one-command-g` worktree on
`readiness/PRIVATE-V1-ONE-COMMAND-001G`, based on exact parent
`90f6f8fede041fd4a7d616c88053d8103700fa64`. No provider body, credential, runtime entry
identifier, squad fact, price or player identity is recorded in repository evidence.

| Gate | Result |
|---|---|
| Parent/ref/worktree | PASS; exact parent, successful parent CI `33576178723`, unrelated dirty root preserved |
| RED regression | PASS; exact-pair and hierarchy public imports/behavior failed before implementation while unrelated focused tests remained green |
| Final focused changed tests | PASS; `72 passed` |
| Full affected markets/ingestion/FPL-points/private/optimiser suite under branch tracing | PASS; `1552 passed` |
| Contract/golden/property/assurance coverage append | PASS; `73 passed` |
| Changed-module branch coverage | PASS; `90.21%` across the eight changed production modules |
| Stage-9 1,000-scenario performance smoke | PASS uninstrumented; `1 passed in 6.98s` |
| PostgreSQL current-market integration population | PASS; `50 passed` against migrated disposable PostgreSQL 18.4; container removed |
| Ruff format/lint | PASS over 743 source, test and script files; zero findings before evidence-only additions |
| Strict mypy | PASS; zero issues in 280 source files |
| Frozen lock/sync | PASS; 40 packages resolved/checked; lock unchanged |
| Build | PASS; `dmf_pulse-0.2.0.tar.gz` and `dmf_pulse-0.2.0-py3-none-any.whl` built |
| External current-market installed-wheel smoke | PASS; external `site-packages`, exact market bundle, zero network calls |
| External Stage-9 installed-wheel smoke | PASS; 343 RECORD members, 32 scenarios; wheel SHA-256 `928509307dab0791a1054ccf342692549757f5a81d00068a6bc3b237a53d1c27` |
| Secret scan | PASS; zero findings |
| Live credential boundary | BLOCKED; Odds key, FPL bearer and runtime entry-ID mechanism are absent from the execution process |
| Retention | PASS; zero provider bodies, credentials, identifiers, squad facts, prices or player identities retained |
| Repository validation | PASS after active PRC-013 and ticket-specific 1,290-file deterministic manifests were refreshed; zero errors |
| Exact final-SHA CI | Pending final push; must not be inferred before the exact SHA run completes |

The first PostgreSQL attempt was intentionally against a fresh database and stopped at absent
schemas; after the packaged Alembic head `20260807_0006` was applied, a second attempt proved the
required TEST-environment guard, and the correctly configured final run passed all 50 tests. No
provider request, FPL authentication, persistent live write, PR, merge, tag or activation occurred.
