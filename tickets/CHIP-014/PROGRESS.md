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
- Resumed session verification on `2026-08-18`: current `origin/main` is still exactly `a8796d4edacea4c87ee6461d381f4df87e1ef39c`.
- The remote Stage-14 branch compares `ahead_by=7`, `behind_by=0` against the immutable parent; merge-base is the immutable parent.
- Remote progress is authoritative and identifies `14.04 Free Hit` as the first unfinished checkpoint.
- Branch created directly from the immutable parent.
- Ordinary container Git transport is unavailable because this execution container cannot resolve `github.com`.
- Durable publication uses authenticated GitHub Git-data/contents APIs with non-force fast-forward updates.
- Every publication is verified by comparing the intended commit with the remote branch ref.
- Temporary `.github/workflows/stage14-workspace-export.yml` remains retained during recovery and must be removed before final delivery.

## Checkpoints

| Checkpoint | Status | Latest pushed capability commit | Direct tests | Notes |
|---|---|---|---|---|
| Bootstrap | COMPLETE | `6b7f1d528a85f474e2affe912b72d6d24881839e` | not applicable | Remote resumable branch and progress record created. |
| 14.01 generic chip definition/inventory | COMPLETE | `3173c97f5d04b3b0fe65c8e9b17876d257b233be` | 58 passed | 98% branch coverage for compiler/inventory. |
| 14.02 captain/vice/Triple Captain | COMPLETE | `8c135cba3efb6d64b9fed7f2bb2e06ebe28ae8f2` | 41 passed | 99% branch coverage for captaincy/TC. |
| 14.03 Bench Boost | COMPLETE | `f1c384972567befbe4713c56bfaaa4a481135687` | 67 passed | 26 new BB tests; 94% combined affected coverage. |
| 14.04 Free Hit | IN_PROGRESS | — | — | Temporary-policy comparator and exact restoration next. |
| 14.05 Wildcard | NOT_STARTED | — | — | — |
| 14.06 scheduler/continuation | NOT_STARTED | — | — | — |
| 14.07 CLI/evaluation/evidence | NOT_STARTED | — | — | — |

## Completed capability

### 14.01 generic definition/inventory

- Closed optimisation effect grammar compiled from accepted rules-layer public views.
- Fail-closed unknown/invalid effects; multiple copies, future acquisition, windows, expiry, selection/cancellation/use, minimum gaps, concurrency and multi-week occupancy.
- Deterministic definition, bundle and inventory semantic hashes.

### 14.02 captain/vice/Triple Captain

- Exact ordered captain/vice search on common coherent Stage-9 scenarios.
- Default delegation to accepted Stage-10 tactical/autosub scoring.
- Conditional vice fallback value and correlated joint nonappearance.
- Rules-bound TC multiplier, independent normal/TC pair optimisation and projected token consumption even at zero extra score.

### 14.03 Bench Boost

- BB score compared with the best normal tactical policy, not a frozen XI.
- Four bench players including goalkeeper; ordinary autosub overlap removed scenario by scenario.
- Natural and engineered routes with explicit hits, budget shift, future-XI, unwind and price-route costs.
- Gross current gain kept separate from net pre-continuation value.
- WC-prepared route measures positive or negative WC-BB synergy; no positive synergy assumption.
- Generic inventory activation and immutable rules/definition/scenario/inventory lineage.

## Validation

Exact commands/results:

- `evidence/tickets/CHIP-014/CHECKPOINT_14_01.md`
- `evidence/tickets/CHIP-014/CHECKPOINT_14_02.md`
- `evidence/tickets/CHIP-014/CHECKPOINT_14_03.md`

Results:

- 14.01: `58 passed`; `98%` branch coverage; compileall `PASS`.
- 14.02: `41 passed`; `99%` branch coverage; compileall `PASS`.
- 14.03: `67 passed` (`41` inherited captaincy/TC + `26` BB); `94%` combined affected branch coverage (`586` statements, `24` missed; `204` branches, `25` partial); compileall/whitespace `PASS`.

Deferred gates remain truthfully unpassed:

- Ruff/mypy: final Stage-14 acceptance.
- Build/wheel/installed CLI: final Stage-14 acceptance.
- Targeted inherited regressions: final dependency scope after all integrations exist.
- Full repository pytest: not run by design.

## Push/equality record

- 14.01 capability `3173c97f5d04b3b0fe65c8e9b17876d257b233be`: remote `identical`, ahead `0`, behind `0`.
- 14.02 capability `8c135cba3efb6d64b9fed7f2bb2e06ebe28ae8f2`: remote `identical`, ahead `0`, behind `0`.
- 14.03 capability `f1c384972567befbe4713c56bfaaa4a481135687`: remote `identical`, ahead `0`, behind `0`.
- Force push: `false` for all capability publications.
- 14.03 publication contained only coherent BB production code, contracts, tests, exports and evidence.
- Container-side Git worktree unavailable; validated offline scratch passed syntax and whitespace checks before publication.

## Known limitations

- No target-season chip-policy performance claim is made yet.
- BB `net_pre_continuation_value` deliberately excludes finite-inventory continuation/opportunity value; checkpoint 14.06 owns that comparison.
- Sophisticated continuation methods remain open by specification and are not claimed solved.
- Temporary branch-only workspace-export workflow remains and must be removed before final delivery.
- Final Ruff, mypy, frozen sync, build, wheel, installed-wheel CLI and targeted inherited regressions remain pending.

## Exact resume state

Resume from remote branch HEAD, verify ancestry, read this file, then continue checkpoint 14.04. Do not recreate or reset checkpoints 14.01–14.03.
