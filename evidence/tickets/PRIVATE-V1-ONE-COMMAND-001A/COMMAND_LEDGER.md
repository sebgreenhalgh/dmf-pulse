# PRIVATE-V1-ONE-COMMAND-001A command ledger

All product commands ran from the isolated `review_pack/one-command` worktree on
`readiness/PRIVATE-V1-ONE-COMMAND-001A`, based on exact parent
`ba87691c559559757e7cb06f06269a85706268a8`. Official-FPL and Odds response bodies, manager
payloads and credentials retained by the real command attempt: zero.

| Gate | Result |
|---|---|
| Parent/ref/worktree/CI preflight | PASS; exact parent and successful parent CI `33495730710`; unrelated dirty root worktree untouched |
| Direct FPL transport and adversarial boundaries | PASS; GET-only allowlist, auth header, redaction, 401/403/404/429, timeout, retry, budget and no-retention paths covered |
| Parser/governance compatibility | PASS; final focused run `88 passed in 1.59s`; frozen FPL-004 identities preserved when direct-only optional fields are unpublished |
| One-command/CLI/Odds/target/candidate focused proof | PASS; final selected run `13 passed in 37.46s`; catalogue ceiling regression `1 passed in 1.81s` |
| Affected ingestion/markets population | PASS; `1149 passed in 397.89s` |
| Affected Stage 7/8/9 population | PASS; `545 passed in 101.71s` |
| Affected optimiser/rules/private population | PASS; `868 passed in 413.44s` |
| Network-blocked provider-shaped source-tree E2E | PASS; actual parsers/services through Stage 7-11, comparator, captaincy and report; `1 passed in 30.85s` after clock/cutoff hardening |
| PostgreSQL 18.4 migration matrix | PASS; base/baseline/head/downgrade/upgrade matrix, metadata drift and preservation checks |
| PostgreSQL integration population | PASS; `155 passed, 151 deselected in 277.68s` |
| Performance population | PASS; `3 passed, 1 deselected in 10.45s` |
| Whole non-performance collection | `4042 passed, 3 deselected in 1814.45s`; three expected pre-seal/isolation failures were stale manifest plus two tests given an in-repository `--basetemp` |
| Post-seal isolation/manifest reruns | PASS; both installed-runtime isolation tests passed with an external temp root; clean-checkout manifest test `1 passed in 1.14s` |
| Ruff format/lint | PASS over `src` and `tests`; zero findings |
| Strict mypy | PASS; zero issues in 280 source files |
| Frozen dependency sync | PASS |
| Build | PASS; `dmf_pulse-0.2.0.tar.gz` and `dmf_pulse-0.2.0-py3-none-any.whl` |
| Dedicated external installed-wheel one-command proof | PASS; module imported from external `site-packages`; `dmf pulse --help` exposed only `--entry-id`; network-blocked synthetic E2E `1 passed in 32.72s`; temporary environment removed |
| Clean-checkout repository validation | PASS; 1,274-file manifests; zero repository errors |
| Secret scan | PASS from clean checkout after sealing; zero findings |
| Genuine operator command | BLOCKED before provider access with exact output `THE_ODDS_API_KEY is missing.`; both required environment credentials absent; provider calls zero |
| Exact final-SHA CI | Pending final push; must not be inferred before the exact SHA run completes |

Diagnostic full-suite attempts that omitted the separate `migration` marker, placed the temp root
inside the repository, or shared one mutable database between two pytest processes were rejected
as gate evidence. No product failure was relabelled successful. The controlling post-seal focused
reruns and exact-final-SHA sharded CI are recorded separately from those diagnostics.
