# CHIP-014 Stage-14 progress

- Ticket: `CHIP-014`
- Stage: `14 — Chip optimisation`
- Immutable original parent: `a8796d4edacea4c87ee6461d381f4df87e1ef39c`
- Branch: `stage/A14/CHIP-014-chip-optimisation`
- Delivery mode: Git-first, resumable checkpoint publication.
- Current engineering status: `IN_PROGRESS — 14.06 COMPLETE / REMOTE; 14.07 NOT_STARTED`
- Human acceptance: `false`
- Merged: `false`
- Accepted tag: none

## Startup and recovery verification

- `origin/main` remained exactly the immutable Stage-14 parent at resume.
- The canonical remote branch was verified through Wildcard capability
  `0449dd7c47ae983a78fb8ef9098ce604ae3022db` before unfinished work resumed.
- The previously reported local scheduler commit
  `3935bc00ff760a6c76bb6115e142aa273affc371` was absent from the recovered
  repository, workspace export, reflog/object store and stash. It is not claimed
  as recovered.
- The reported 14.07 stash was also absent. Checkpoint 14.07 will be implemented
  from the published 14.06 state, not reconstructed from an invented stash.
- Checkpoint 14.06 was reimplemented only, using recovered uncommitted remnants
  as guidance; checkpoints 14.01–14.05 were not rebuilt.
- Ordinary Git network transport is unavailable in this execution environment.
  Authenticated GitHub contents/workflow transport remains temporarily retained
  for non-force checkpoint publication and will be removed before final handoff.

## Checkpoints

| Checkpoint | Status | Latest pushed capability commit | Direct verification | Notes |
|---|---|---|---|---|
| Bootstrap | COMPLETE | `6b7f1d528a85f474e2affe912b72d6d24881839e` | not applicable | Resumable branch/progress record. |
| 14.01 generic chip definition/inventory | COMPLETE | `3173c97f5d04b3b0fe65c8e9b17876d257b233be` | 58 passed | Compiler/inventory contracts. |
| 14.02 captain/vice/Triple Captain | COMPLETE | `8c135cba3efb6d64b9fed7f2bb2e06ebe28ae8f2` | 41 passed | Joint captain/vice/TC evaluator. |
| 14.03 Bench Boost | COMPLETE | `f1c384972567befbe4713c56bfaaa4a481135687` | 67 passed | Natural/engineered BB routes. |
| 14.04 Free Hit | COMPLETE / REMOTE | `ef3f5b2` | 23 focused; 149 then-current chip tests | Best temporary versus best normal policy; exact restoration. |
| 14.05 Wildcard | COMPLETE / REMOTE | `0449dd7c47ae983a78fb8ef9098ce604ae3022db` | 58 focused; 207 then-current chip tests | Immediate/delayed/FH-bridge/hold routes. |
| 14.06 scheduler/continuation | COMPLETE / REMOTE | `cc62e21a3a085fc6a5cec959881f075f6dfa13c1` | 75 focused; 282 all chip unit/property | Exact/beam finite-inventory policy, diagnostics, nonanticipativity and oracle. |
| 14.07 service/replay/CLI/artifacts | NOT_STARTED | — | — | Must not start before 14.06 remote verification. |
| Final acceptance/evidence/cleanup | NOT_STARTED | — | — | Includes transport cleanup; no PR/merge/tag. |

## 14.06 completed capability

- Immutable scheduler request, opportunity, scenario, objective, policy,
  disposition, diagnostic and lineage contracts.
- Exact exhaustive/dynamic search below a configurable state threshold.
- Deterministic bounded beam search above the threshold.
- Finite inventory, multiple copies, windows, expiry, duration, concurrency,
  minimum gaps, one-use and duplicate-token rejection.
- Expected, robust/risk-adjusted and cash-like terminal-state objectives.
- Common-scenario alignment and sealed current-cutoff-only inputs.
- Explicit use-now, delay, never-use, `HOLD` and `EXPIRE_UNUSED` comparison.
- Prefix-sensitive state identity and finite-state optimistic bounds.
- Perfect-information diagnostic upper bound isolated from executable policy.
- Correct per-Gameweek concurrency enforcement for staggered intervals.

Evidence: `evidence/tickets/CHIP-014/CHECKPOINT_14_06.md`.

## 14.06 validation

- Focused scheduler unit/property: `75 passed`.
- Complete current chip unit/property: `282 passed`.
- `schedule_models.py` branch-only coverage: `145 / 154` = `94.155844%`;
  coverage.py branch-mode raw line+branch ratio: `96.896552%`.
- `scheduler.py` branch-only coverage: `149 / 154` = `96.753247%`;
  coverage.py branch-mode raw line+branch ratio: `97.972973%`.
- Combined scheduler branch-only coverage: `294 / 308` = `95.454545%`;
  combined raw line+branch ratio: `1142 / 1172` = `97.440273%`.
- Entire chip package raw line+branch ratio: `3300 / 3461` = `95.348165%`.
- Direct `free_hit.py` raw line+branch ratio: `171 / 185` = `92.432432%`;
  this is not inferred from package aggregate coverage.
- Changed-file Ruff format/lint: PASS.
- Strict mypy for changed production modules: PASS.
- Compileall: PASS.
- `git diff --check`: PASS.

These percentages are deliberately distinguished: per-module raw branch
coverage is not represented as aggregate package coverage.

## Remaining mandatory work

1. Implement checkpoint 14.07 service, sequential replay, CLI and artifacts from
   published scheduler capability `cc62e21a3a085fc6a5cec959881f075f6dfa13c1`.
2. Run the bounded Stage-14 test/static/build/installed-wheel matrix and targeted
   inherited regressions.
3. Publish checkpoint 14.07.
4. Produce final evidence, remove all transient Stage-14 recovery/transport
   workflows and `recovery/`, validate/secret-scan, then publish final cleanup.

`FULL_REPOSITORY_PYTEST = NOT_RUN_BY_DESIGN — DEFERRED_TO_INDEPENDENT_SOL_REVIEW`
unless a later bounded reason is recorded.

## Known limitations

- No target-season chip-policy performance claim is made.
- Checkpoint 14.06 consumes explicit opportunity/scenario values; checkpoint
  14.07 owns the public service/replay composition and artifact surface.
- Final repository-wide static/build/installed-wheel/secret-scan gates remain
  pending.
- Temporary Stage-14 publication/recovery material remains only because it is
  still required to publish the remaining checkpoints; it is not product code.
- No PR, merge, accepted tag or human acceptance has occurred.

## Exact resume state

- Published scheduler capability: `cc62e21a3a085fc6a5cec959881f075f6dfa13c1`.
- The exported canonical bundle resolves the Stage-14 branch capability ref to
  that SHA; scheduler production, test and evidence blobs match the validated
  local Git hashes.
- Reported scheduler commit `3935bc00ff760a6c76bb6115e142aa273affc371`: not recovered.
- Reported 14.07 stash `stage14-service-cli-replay-wip-after-scheduler`: not recovered.
- Recovery mode: truthful Case B; only checkpoint 14.06 was reconstructed.
- Checkpoint 14.07 starts from the published `cc62e21a...` canonical tree.
- Temporary Stage-14 transport/export workflows and `recovery/` remain only until final cleanup.
