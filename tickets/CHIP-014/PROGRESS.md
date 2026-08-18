# CHIP-014 Stage-14 progress

- Ticket: `CHIP-014`
- Stage: `14 — Chip optimisation`
- Immutable original parent: `a8796d4edacea4c87ee6461d381f4df87e1ef39c`
- Branch: `stage/A14/CHIP-014-chip-optimisation`
- Delivery mode: Git-first, resumable checkpoint publication.
- Current engineering status: `IN_PROGRESS`
- Human acceptance: `false`
- Merged: `false`
- Accepted tag: none

## Startup verification

- `origin/main` at branch creation: `a8796d4edacea4c87ee6461d381f4df87e1ef39c`.
- Branch created directly from the immutable parent.
- Ordinary container Git transport is unavailable because this execution container cannot resolve `github.com`.
- Durable publication uses authenticated GitHub Git-data/contents APIs with non-force fast-forward updates.
- Every publication is verified by comparing the intended commit with the remote branch ref.

## Checkpoints

| Checkpoint | Status | Latest pushed capability commit | Direct tests | Notes |
|---|---|---|---|---|
| Bootstrap | COMPLETE | `6b7f1d528a85f474e2affe912b72d6d24881839e` | not applicable | Remote resumable branch and progress record created. |
| 14.01 generic chip definition/inventory | COMPLETE | `3173c97f5d04b3b0fe65c8e9b17876d257b233be` | 58 passed | 98% branch coverage for Stage-14 compiler/inventory production code. |
| 14.02 captain/vice/Triple Captain | IN_PROGRESS | — | — | Joint captain/vice and TC common-scenario evaluator next. |
| 14.03 Bench Boost | NOT_STARTED | — | — | — |
| 14.04 Free Hit | NOT_STARTED | — | — | — |
| 14.05 Wildcard | NOT_STARTED | — | — | — |
| 14.06 scheduler/continuation | NOT_STARTED | — | — | — |
| 14.07 CLI/evaluation/evidence | NOT_STARTED | — | — | — |

## Checkpoint 14.01 completed capability

- Generic optimisation-facing chip definitions and closed effect grammar.
- Rules-view adapter that stores ruleset ID/version/hash without copying target-season constants.
- Fail-closed unknown-effect and invalid-semantics compilation.
- Inventory grants/tokens, multiple copies, future acquisition, windows, expiry and exclusions.
- Pending selection, cancellation, activation, use, minimum gaps, concurrency groups/limits and multi-week occupancy.
- Deterministic semantic hashes for definitions, bundles and inventory state.
- Synthetic tests for multi-week, transfer-cost, budget, unknown-effect and conflicting-duration chips.

## Checkpoint 14.01 validation

Commands and exact results are retained in `evidence/tickets/CHIP-014/CHECKPOINT_14_01.md`.

- Focused unit/property tests: `58 passed`.
- Stage-14 compiler/inventory branch coverage: `98%` (`439` statements, `3` missed; `156` branches, `9` partial).
- Python compileall for affected source/tests: `PASS`.
- `git diff --check` equivalent on the publication manifest: `PASS`.
- Ruff/mypy: not run at this checkpoint; deferred to final acceptance and not relabelled as passed.
- Full repository pytest: not run by design.

## Push/equality record

- Capability commit: `3173c97f5d04b3b0fe65c8e9b17876d257b233be`.
- Remote comparison immediately after publication: `identical`, ahead `0`, behind `0`.
- Force push: `false`.
- Publication tree contained only coherent 14.01 capability/tests/evidence.
- Container-side Git worktree: not available. The offline validation scratch contained isolated 14.02 work after 14.01 validation; it was not included in the 14.01 publication tree.

## Known limitations

- No target-season policy performance claim is made by checkpoint 14.01.
- Sophisticated continuation-value selection remains open by specification and is not claimed solved.
- Temporary branch-only workspace-export workflow remains and must be removed before final delivery.
- Final Ruff, mypy, frozen sync, build, wheel, installed-wheel CLI and targeted inherited regressions remain pending.

## Exact resume state

Resume from remote branch HEAD, verify it descends from the immutable parent, read this file, then continue checkpoint 14.02. Do not recreate or reset checkpoint 14.01.
