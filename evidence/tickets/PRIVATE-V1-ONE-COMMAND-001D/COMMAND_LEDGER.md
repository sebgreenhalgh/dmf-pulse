# PRIVATE-V1-ONE-COMMAND-001D command ledger

All product commands ran from the isolated `review_pack/one-command-d` worktree on
`readiness/PRIVATE-V1-ONE-COMMAND-001D`, based on exact parent
`876b451c7a44502f965fa83f9601f79dcfe816b0`. No response content, runtime entry identifier or
credential value is recorded in repository evidence.

| Gate | Result |
|---|---|
| Parent/ref/worktree | PASS; exact parent, successful parent CI `33562042171`, unrelated dirty root preserved |
| Starting live failure | VERIFIED from immutable parent evidence: bootstrap and fixtures parsed, then current game-settings rejected parser-produced Decimal |
| Red/green adapter regression | Parent implementation: 8 expected failures and 10 passes; fixed implementation: `18 passed` |
| Parser/current focused regression | PASS; `129 passed in 1.69s` |
| Focused current/direct/one-command/CLI | PASS; `201 passed in 40.01s` |
| Changed-module branch coverage | PASS; `84 passed`; current module 92% combined line/branch coverage and every new line/branch covered |
| Affected ingestion unit population | PASS; `985 passed in 148.77s` |
| Private-v1 and affected CLI population | PASS; `73 passed in 67.11s` |
| Diagnostic database population | Not an acceptance gate; 990 non-setup cases passed, then 75 PostgreSQL-marked cases reported the absent `DMF_TEST_DATABASE_URL` fixture |
| Ruff format/lint | PASS over 730 source, test and script files; zero findings |
| Strict mypy | PASS; zero issues in 280 source files |
| Frozen sync/lock | PASS; Python 3.13 frozen environment and lock check unchanged |
| Build | PASS; wheel and sdist built with the pinned build environment |
| External installed-wheel projection | PASS outside the repository; nested Decimal values normalized exactly and source tree was not imported |
| Real source-tree current compilation | PASS on Windows/Python 3.13.9; endpoint classes `BOOTSTRAP`, `FIXTURES`; target GW3; canonical game-settings JSON 1,052 bytes |
| Real installed-wheel current compilation | PASS outside the repository; endpoint classes `BOOTSTRAP`, `FIXTURES`; same target GW3 and same game-settings semantic hash |
| Public-first snapshot progression | PASS for this ticket; `BOOTSTRAP`, `FIXTURES`, `ENTRY`, `HISTORY`, `TRANSFERS`, `PICKS`, then `CREDENTIAL_MISSING: DMF_FPL_BEARER_TOKEN is missing.` |
| Genuine one-command retry | BLOCKED with exact output `THE_ODDS_API_KEY is missing.`; both credential-presence flags false; no Odds change or synthetic relabelling |
| Repository validation and secret scan | PASS; deterministic 1,282-file manifests, zero repository errors and zero secret findings |
| Exact final-SHA CI | Pending final push; must not be inferred before the exact SHA run completes |

Live hashes are transient observations and may change between reads. No provider body, runtime
entry identifier, credential, cache or replay artifact was written.
