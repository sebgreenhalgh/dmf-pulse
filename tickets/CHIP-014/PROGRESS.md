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
| 14.02 captain/vice/Triple Captain | COMPLETE | `8c135cba3efb6d64b9fed7f2bb2e06ebe28ae8f2` | 41 passed | 99% branch coverage for captaincy/TC production code. |
| 14.03 Bench Boost | IN_PROGRESS | — | — | Incremental common-scenario BB comparator next. |
| 14.04 Free Hit | NOT_STARTED | — | — | — |
| 14.05 Wildcard | NOT_STARTED | — | — | — |
| 14.06 scheduler/continuation | NOT_STARTED | — | — | — |
| 14.07 CLI/evaluation/evidence | NOT_STARTED | — | — | — |

## Completed capability

### Checkpoint 14.01

- Generic optimisation-facing chip definitions and closed effect grammar.
- Rules-view adapter that stores ruleset ID/version/hash without copying target-season constants.
- Fail-closed unknown-effect and invalid-semantics compilation.
- Inventory grants/tokens, multiple copies, future acquisition, windows, expiry and exclusions.
- Pending selection, cancellation, activation, use, minimum gaps, concurrency groups/limits and multi-week occupancy.
- Deterministic semantic hashes for definitions, bundles and inventory state.
- Synthetic tests for multi-week, transfer-cost, budget, unknown-effect and conflicting-duration chips.

### Checkpoint 14.02

- Exact ordered captain/vice search on common coherent Stage-9 scenarios.
- Default delegation to the accepted Stage-10 tactical/autosub evaluator.
- Conditional vice fallback probability and incremental fallback value.
- Correlated captain/vice nonappearance and fixture/postponement context retained.
- Triple Captain multiplier compiled from the rules-bound chip definition.
- Independently optimised normal and TC captain/vice policies on identical scenarios.
- Projected generic inventory activation; a zero-extra TC outcome still consumes the token.
- Immutable ruleset, definition, scenario-set and before/after inventory lineage.

## Validation

Exact commands and results are retained in:

- `evidence/tickets/CHIP-014/CHECKPOINT_14_01.md`
- `evidence/tickets/CHIP-014/CHECKPOINT_14_02.md`

Checkpoint 14.01:

- Focused unit/property tests: `58 passed`.
- Stage-14 compiler/inventory branch coverage: `98%` (`439` statements, `3` missed; `156` branches, `9` partial).
- Python compileall: `PASS`.

Checkpoint 14.02:

- Focused captaincy/TC tests: `41 passed`.
- Captaincy/TC branch coverage: `99%` (`303` statements, `2` missed; `104` branches, `2` partial).
- Python compileall: `PASS`.
- Publication whitespace/diff check: `PASS`.

Deferred gates remain truthfully unpassed:

- Ruff/mypy: final Stage-14 acceptance.
- Build/wheel/installed CLI: final Stage-14 acceptance.
- Targeted inherited regressions: final dependency scope after all integrations exist.
- Full repository pytest: not run by design.

## Push/equality record

Checkpoint 14.01:

- Capability commit: `3173c97f5d04b3b0fe65c8e9b17876d257b233be`.
- Remote comparison: `identical`, ahead `0`, behind `0`.

Checkpoint 14.02:

- Capability commit: `8c135cba3efb6d64b9fed7f2bb2e06ebe28ae8f2`.
- Remote comparison immediately after publication: `identical`, ahead `0`, behind `0`.
- Force push: `false`.
- Publication tree contained only coherent 14.02 production code, focused tests, exports and evidence.
- Container-side Git worktree: unavailable; the validated offline scratch was checked for trailing whitespace and syntax before publication.

## Known limitations

- No target-season policy performance claim is made by checkpoints 14.01–14.02.
- Gross Triple Captain current gain is intentionally distinct from continuation/opportunity value, which is implemented in checkpoint 14.06.
- Sophisticated continuation-value selection remains open by specification and is not claimed solved.
- Temporary branch-only workspace-export workflow remains and must be removed before final delivery.
- Final Ruff, mypy, frozen sync, build, wheel, installed-wheel CLI and targeted inherited regressions remain pending.

## Exact resume state

Resume from remote branch HEAD, verify it descends from the immutable parent, read this file, then continue checkpoint 14.03. Do not recreate or reset checkpoints 14.01 or 14.02.
