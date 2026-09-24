# L4 Phase A offline acceptance

The exact L4 authority passes only with its exact attestation and current provider
profile hashes. L1/L2/L3 remain consumed. The Odds capability matrix, terms, account,
geography, unresolved rights and zero-retention boundary are unchanged. FPL and
OpenFootball rights files are byte-identical to parent
`433d7160c0f15588009aff44acc1dd479cb8982d`.

The unchanged FPL purpose was independently inspected: it permits low-volume,
operator-initiated, read-only private recommendation use, with automated access,
transient processing and private internal use allowed; raw/cache/derived storage,
backup, redistribution, public display and training are denied; retention is zero and
unresolved rights are empty. Its file SHA is
`1691229b120054b8d4c65c7d74e5a0f6d9d11947f1a8f261d26649314268011d` and semantic
profile SHA is `f319842091b89b0f8cc207b681d2584e1cce282e570d5d4daba92b06ae85f095`.

No credentials were inspected and no FPL, Odds, or live OpenFootball request was made.
D1/D2/D3 protected behavior and all model/optimizer mathematics are unchanged except
the necessary L4 terminal identity in the wrapper.

## Verification

- Frozen offline environment: 40 packages.
- Exact L4 authority, rights, D1/D2/D3 wrapper and inherited focused population:
  208 passed.
- Generated end-to-end observation plus five bounded 001P cases: 6 passed.
- Public readiness, Stage 8/9/10/11, rolling, one-command, and comparison regressions:
  167 passed.
- Combined relevant test count: 381 passed.
- Repository-wide Ruff format/check: 905 files formatted; all checks passed.
- Strict mypy: 313 source files passed.
- Wheel and sdist build from the frozen environment: passed.
- Clean installed-wheel verification outside the source tree: passed; exact L4
  authority valid, L1/L2/L3 consumed, provider calls 0, production activation false.
- Canonical PRC-013 and L4 manifests: 1,535 governed files each; manifest tests passed.
- Repository validation: passed with 0 errors.
- Capped deterministic review archive: 18 entries.
- Independent review: no P0, P1 or material P2 findings; conditional verdict
  `CLEAR_FOR_CURRENT_TEAM_STRENGTH_001P_L4_ONE_SHOT_EXECUTION`.
- `git diff --check`: passed.
- First-party secret scan: passed with 0 findings.

The retained public readiness authenticated as `DEGRADED`, `missing_due=0`,
`LIVE_OBSERVED`, and correctly reuses the already sealed artifact without a refit claim.
The private-provider request count is zero for FPL and Odds. L4 remains unconsumed.
