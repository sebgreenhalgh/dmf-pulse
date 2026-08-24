# LIVE-ODDS-INTEGRATION-001 acceptance contract

This ticket authorizes only the reviewed two-parent integration of accepted LIVE-ODDS commit
`5e55cf3361a1abff4b2e32dcc30fe42900ea2e16` onto repaired main
`fceca02d21ec7031e36518c46724c6a6d3d6c72e`. It authorizes no LIVE-ODDS product development,
accepted-source rewrite, replacement pull request, merge to main, human acceptance, or production
activation.

## A. Git identity

1. The integration branch starts exactly at `fceca02d21ec7031e36518c46724c6a6d3d6c72e`.
2. The one implementation commit is a merge whose second parent is exactly
   `5e55cf3361a1abff4b2e32dcc30fe42900ea2e16`.
3. The merge has exactly two parents; squash, rebase, cherry-pick, and flattened reconstruction are
   forbidden.
4. The common base remains `baed47bce7a158d91afe38351a2c65be60444adf`.

## B. Conflict confinement

1. The complete observed conflict set is exactly `PLANS.md` and
   `evidence/tickets/PRC-013/current_manifest.json`.
2. No executable conflict is permitted under `src/`, `config/`, `tests/`, `scripts/`, or `.github/`.
3. Novel reconciliation paths are limited to the two conflict paths and this ticket's new
   ticket/evidence namespace.
4. Every other integrated path must arise naturally and exactly from one parent.

## C. Governance resolution

1. `PLANS.md` retains the exact repaired-main programme first, the exact accepted LIVE-ODDS
   programme second, the unchanged shared history, and the accepted LIVE-ODDS review tail.
2. The PRC-013 active manifest is regenerated from the final combined candidate through the
   canonical first-party generator. Neither parent is selected and no hash is manually spliced.
3. No historical LIVE-ODDS, CI-FPL, CI-TEST, or CI-COVERAGE evidence or manifest is rewritten.

## D. Exact blob identity

1. All 20 protected LIVE-ODDS substantive blobs equal the accepted second parent.
2. All 16 protected repaired-main substantive blobs equal the first parent.
3. Exact identity is checked before and after the merge commit; any mismatch blocks publication.

## E. Validation

The complete focused LIVE-ODDS matrix, repaired-main/FPL regressions on PostgreSQL 18.4, frozen
sync, format, lint, strict mypy, build, general/ODD/GCS wheel checks, repository validation, secret
scan, scope audit, and canonical eight-shard population audit must pass. The automatic final-SHA
push run must pass Pre-flight, all eight shards, combined coverage, post-coverage, and the stable
Python 3.13 / Ubuntu sentinel without timeout or cancellation.

## F. Acceptance boundary

Human acceptance of `5e55cf...` remains acceptance of that capability source only. The integration
merge requires its own independent review and later human decision. The maximum post-CI engineering
status is `LIVE_ODDS_INTEGRATION_IMPLEMENTED_PENDING_INDEPENDENT_REVIEW`.
