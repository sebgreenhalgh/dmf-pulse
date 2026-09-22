# 001P.04 — locked real synthetic cases and installed wheel

All five locked cases passed: `test_team_strength_shadow_cases.py`, 5 passed in
700.86 seconds. They use real prepared Stage 7 and real Stage 8/9/10/11, not mocked
optimisation. Case A also reverses world execution order. Expectations were fixed
before this acceptance rerun; ordinary tests never regenerate them.

| Case | League decision | Team-strength decision | Material player/GW rows | Utility delta | Classification |
|---|---|---|---:|---:|---|
| A | Hold all three GWs | Hold; same complete tactics | 23/360 | -1 | PLAYER_PROJECTION_MATERIAL_BUT_DECISION_ROBUST |
| B | Hold | One goalkeeper transfer now | 68/360 | -5 | TEAM_STRENGTH_ROOT_ACTION_MATERIAL |
| C | Hold root; goalkeeper transfer GW7 | Hold root; same transfer GW6 | 55/360 | +21 | ROOT_ACTION_ROBUST_CONTINUATION_SENSITIVE |
| D | Hold | Hold; captain and XI change | 126/360 | +52 | ROOT_ACTION_ROBUST_TACTICS_SENSITIVE |
| E | Screened goalkeeper transfer now | Hold root; transfer GW7 | 126/360 | +50 | CANDIDATE_SCREEN_CONFOUNDED |

Each has 120 synthetic players, 360 player/GW projections, nine fixtures, and the
same controls across worlds. Three GW5 fixtures have markets; the six GW6/GW7
fixtures are prior-only. Case E changes the canonical screen as a downstream
consequence, with identical screening policy. No candidate equality is forced.

These are deliberately small ONE-DRAW synthetic control/decision demonstrations,
not calibrated live xP or prospective model-value evidence. Generated source
variants do not alter accepted model policy or historical hyperparameter selection.
Action signatures include FT/bank trajectories: in B these future state signatures
change after the root transfer even though both worlds make no later transfer.

`verify_team_strength_shadow_cases.py --output <report>` is an explicit offline
evidence command for these same locked cases; it does not update expectations.

## Direct coverage and regression

- Fresh direct population: **64 passed in 712.19 seconds**.
- New production modules: **484/484 statements; 124/124 branches = 100%**.
- Zero excluded lines, missing branches or partial branches. A fresh independent
  coverage data file was used, not appended data from older source revisions.
- Final-source separate-process default-private regression against exact f39:
  PASS. Decision/report/projection/optimiser content matches. Only propagated
  package-provenance hashes and bijective information-set IDs are normalised in
  the diagnostic; production authentication is unchanged.
- Current-tree public preservation: all 87 public-owned files match 6b96 exactly;
  only the two private seams and three new private modules differ in scoped
  production paths. Ordinary pulse/CLI, availability, points and optimiser unchanged.

## Installed-wheel demonstration

Frozen offline sync and wheel/sdist build pass. The new verification script installs
the wheel with locked runtime-only dependencies into a fresh environment outside
the repository. It then runs the actual two-world B comparison with network blocked:
120 players, root-action material classification, utility delta -5, provider requests
during solves zero. See `installed_wheel_comparison.json`.

The accepted public 001A replay and public installed-wheel model reproduction also
passed at .01; its implementation remains exact. No provider acquisition, private
live retention, ordinary activation, PR, merge or tag occurred. Whole-ticket fresh
review and exact-final-SHA CI remain final acceptance gates.
