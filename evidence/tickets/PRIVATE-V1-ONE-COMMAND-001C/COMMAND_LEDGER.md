# PRIVATE-V1-ONE-COMMAND-001C command ledger

All product commands ran from the isolated `review_pack/one-command-c` worktree on
`readiness/PRIVATE-V1-ONE-COMMAND-001C`, based on exact parent
`52480d61bcc7aab52441cc310a7f946510dae5de`. No response content, entry identifier or credential
value is recorded in repository evidence.

| Gate | Result |
|---|---|
| Parent/ref/worktree | PASS; exact parent, successful parent CI `33556684536`, unrelated dirty root preserved |
| Parent live reproduction | PASS as a diagnostic; one public bootstrap request returned 1,670,303 bytes, then semantic hashing raised `TypeError: Object of type Decimal is not JSON serializable` |
| Red/green parser regression | Parent behavior: 4 new failures and 37 inherited passes; fixed parser: final `45 passed` |
| Frozen FPL semantic hashes | PASS; bootstrap `9bad2f61...f5e2e` and fixtures `450e9876...345a7` remain unchanged |
| Focused parser/current/direct/one-command/CLI | PASS; `183 passed in 39.40s` |
| Affected ingestion population | PASS; `967 passed in 141.56s` |
| Parser branch coverage | PASS; 45 tests, 95.82% combined line/branch coverage; every new recursive branch covered |
| Generic canonical serializer regression | PASS; production serializer untouched and 15 assurance tests passed |
| Real source-tree bootstrap parse | PASS on Windows/Python 3.13.9; 1,670,324 bytes, target GW3, semantic SHA-256 `76e05dd6cd55bdf27edebb831a8556710b8b4762d39074ef26a1ab0148fccc4f` |
| Public-first snapshot progression | PASS for this ticket; two requests reached `BOOTSTRAP`, then `FIXTURES`; next separate blocker is `INTERNAL_INVARIANT: FPL game settings are invalid` in the current-input adapter |
| Ruff format/lint | PASS over 729 source, test and script files; zero findings |
| Strict mypy | PASS; zero issues in 280 source files |
| Frozen sync and build | PASS; frozen Python 3.13 environment, wheel and sdist built |
| External installed-wheel proof | PASS outside the repository; nested Decimal remained exact, artifact was JSON-safe, and a real public bootstrap parsed and hashed |
| Genuine one-command retry | BLOCKED with exact output `THE_ODDS_API_KEY is missing.`; both credential-presence flags false; no Odds change or synthetic relabelling |
| Repository validation and secret scan | PASS; deterministic 1,279-file manifests, zero repository errors and zero secret findings |
| Exact final-SHA CI | Pending final push; must not be inferred before the exact SHA run completes |

Live bootstrap bytes and semantic hashes are transient observations and may change between reads.
No provider body, runtime entry identifier, credential, cache or replay artifact was written.
