# RUL-002R4 review handoff (no GitHub write performed)

## Summary

RUL-002R4 remediates the remaining PLAYER_POINTS static-review P1 on branch
`stage/R2/FPL-2026-27-rules`, based on accepted commit
`9d7c360ab6a4cc7bfc6d6f41e44be6b47512b272`. It preserves the accepted Stage-9
integration while routing generated target-schema-v1.1 assist facts through the
compiled 2026/27 assist policy before a player event vector receives an assist.

## Material integration changes

- Generated OPEN_PLAY, OPPONENT_OWN_GOAL, PENALTY, and DIRECT_FREE_KICK assist
  candidates carry an immutable `AssistDecisionContext`.
- `AcceptedRulesAdapter` calls `dmf_pulse.rules.assists.classify_assist`; allocation
  increments `eligible_assists` only after a definite compiled-rule decision.
- Target-schema-v1.1 exact scoring rejects unresolved `AMBIGUOUS_ASSIST` goals;
  legacy v1.0 TEMP-EVT-002 ambiguity behaviour remains compatible.
- Generated penalty, direct-free-kick, and own-goal assist tests exercise allocation,
  adapter, scorer, reconciliation, and target service paths. Existing A-R policy
  goldens, BPS/save regressions, and capability scope remain covered.

## Production status

Target 2026/27 global status remains `CAPTURED_UNVERIFIED`,
`production_eligible=false`, and not ACTIVE. PLAYER_POINTS alone is source-backed,
ready, and production eligible with capability hash
`68898c5c9c4f2e2b14001cc1a1625a169eb9858fe20b7e31a45c359077bdec51`; the ruleset
hash remains `c9fee6287bcb12170aa2f046d486dd812cfa0404efe214344e39f5aeb739cccf` and
approved bonus-tie interpretation hash remains
`dfe10d4dabf8183c10f4a61d3bd2361bd54ee78d24c96ee9d38da42becfbaa49`.

## Exclusions

No optimiser, manager-state transform, captaincy, chips, autosubs, transfer hits,
rank/EO, price model, migration, advanced prop reconciliation, full event tree, or
production BPS residual model.

TEMP-EVT-002 ordinary save generation remains position-GK-only despite the rules/event
contract supporting temporary non-GK goalkeeping; this is documented as nonblocking.

Focused R4 verification is recorded in `IMPLEMENTATION_RESULT.md`. This file is local
handoff material only: the GitHub PR body was not changed. An authorised operator may
apply `gh pr edit 4 --body-file PR_DESCRIPTION.md` after independent rereview.

Executed R4 gates: focused allocation/adapter/service tests (63 passed), rules and
capability regressions (49 passed), Stage-9 affected suite (109 passed), repository
Ruff and mypy, deterministic PLAYER_POINTS recompilation, and the first-party secret
scan. No complete PostgreSQL regression was run because this patch has no persistence
or migration scope.
