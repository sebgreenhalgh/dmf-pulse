# PRIVATE-V1-ONE-COMMAND-001B command ledger

All product commands ran from the isolated `review_pack/one-command-b` worktree on
`readiness/PRIVATE-V1-ONE-COMMAND-001B`, based on exact parent
`4aa187a7ada60523b5df29856e7e55697e310112`. No response content, entry identifier or credential
value is recorded in repository evidence.

| Gate | Result |
|---|---|
| Parent/ref/worktree | PASS; exact parent, successful parent CI `33548371605`, unrelated dirty root preserved |
| Parent Windows reproduction | PASS as a diagnostic; Python 3.13.9 `DirectFplClient` returned `SOURCE_UNAVAILABLE` for public bootstrap |
| Metadata-only lifecycle diagnosis | Confirmed 26 successful chunks and 1,670,370 bytes before closed-socket `settimeout()` raised on EOF iteration 27; temporary diagnostic removed |
| Red/green semantic regression | Parent: `1 failed, 14 passed`; fixed transport: final transport module `22 passed`; complete multichunk body survives socket detach while genuine and truncated declared-body failures remain typed |
| Focused direct/payload/one-command/CLI proof | PASS; final `56 passed in 51.00s` |
| Affected ingestion population | PASS; final `959 passed in 145.80s` |
| Affected private-v1 and pulse CLI population | PASS; final `53 passed in 63.79s` |
| Changed-module branch coverage | PASS; `41 passed in 1.34s`; all new socket-lifecycle and declared-length lines covered; direct module 91% in this bounded population |
| Real source-tree Windows reads | PASS through final `DirectFplClient`; bootstrap 1,670,424 bytes and fixtures 164,155 bytes; values observed, not hardcoded |
| Ruff format/lint | PASS over `src` and `tests`; zero findings |
| Strict mypy | PASS; zero issues in 280 source files |
| Build | PASS after the sandbox-blocked build-isolation download was rerun with network approval; wheel and sdist built |
| External installed-wheel Windows reads | PASS from final external `site-packages`; bootstrap 1,670,424 bytes and fixtures 164,155 bytes; disposable environment removed |
| Genuine one-command retry | BLOCKED with exact output `THE_ODDS_API_KEY is missing.`; both credential-presence flags false; no secret printed and Odds unchanged |
| Repository validation and secret scan | PASS; deterministic 1,277-file manifests, zero repository errors and zero secret findings |
| Exact final-SHA CI | Pending final push; must not be inferred before the exact SHA run completes |

The live bootstrap payload varied from 1,670,370 to 1,670,424 bytes across verification reads; no
payload-size constant or provider response was added to the repository. The failed unprivileged
isolated-build attempt is infrastructure diagnosis, not acceptance evidence; the same literal
build succeeded when its pinned build dependency could be downloaded.
