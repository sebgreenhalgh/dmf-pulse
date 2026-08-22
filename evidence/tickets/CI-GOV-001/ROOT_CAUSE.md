# CI-GOV-001 root cause

Status: `CONFIRMED_FROM_GITHUB_ACTIONS`

## Separation from the product defect

CI-FPL-REPLAY-001 fixed the inherited deterministic replay-clock defect separately at remote
technical head `652bae84fba9bdfbf435367d6140270fa8378d57`. This governance branch intentionally stacks on
that exact tree so it tests the corrected product without depending on local-only evidence commit
`244feb...`.

## Empirical failure

GitHub Actions run `32598102993`, job `97092109564`, used the repository's existing 35-minute
quality-job limit. Its migration matrix passed, and PostgreSQL 18.4 integration completed at
`118 passed, 140 deselected` in 186.59 seconds. The next branch-coverage step began at
`2026-08-22T20:59:57Z` and was canceled at `2026-08-22T21:31:07Z` when the whole job exhausted its
budget. No real pytest failure was emitted before termination.

The cancellation prevented performance, FPL/Odds, GCS, rules, build, wheel, repository validation,
and secret scan from receiving results. This is execution-budget exhaustion, not a test failure,
migration failure, or product regression.

## Correction

The owner explicitly authorizes changing only `timeout-minutes: 35` to `60`. Sixty minutes retains
a hard failure bound while adding 25 minutes of execution headroom. It does not remove, split,
shorten, reorder, retry, or weaken any gate. It is an authorized bounded operational budget, not a
claim of mathematical minimality.
