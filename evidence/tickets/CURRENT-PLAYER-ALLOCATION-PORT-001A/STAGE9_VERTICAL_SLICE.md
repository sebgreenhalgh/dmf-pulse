# Stage7 -> Stage8 -> player allocation -> Stage9 proof

## Public-contract path

`tests/integration/fpl_points/test_current_player_allocation_port.py` executes this complete
offline path without a private scoring shortcut:

1. A strict `ManualFixtureMinutesInput` is compiled by `build_manual_minutes_override` into the
   existing `PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1` Stage-7 projections.
2. `Stage7MinutesContext.from_projections` binds the exact home/away projection hashes.
3. The context is validated by a real `ScoreDistributionRequest`, and
   `ScoreDistributionService.project()` produces the authoritative current Stage-8 distribution.
4. A synthetic official-FPL bootstrap is compiled by `CurrentFplInputService`. Exact official
   element/team identities map to the same 46 canonical Stage-7 UUIDs without names or fuzzy
   matching.
5. `build_player_prior_identity_binding` validates those current identities against the pinned
   donor lineage. `build_participation_scenario` validates one coherent manual minutes path.
6. `bind_fixture_allocation_profiles` adapts the governed donor values to that exact participant
   universe and emits observable artifact, acceptance, current-bundle, and identity-binding
   hashes.
7. `FplPointsService.project()` samples only from the Stage-8 score cells, allocates coherent
   events, sends each `FixtureEventScenario` to the accepted current rules adapter, and emits
   integer scenario scores, a joint player matrix, and marginal summaries.

The companion regression executes the existing
`REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1` Stage-7 path through the same Stage-9 service.

## Assertions

- Every scenario contains exactly `home_goals + away_goals` goal events, split exactly by the
  authoritative Stage-8 home/away score.
- Every scorer, assister, own-goal player, penalty taker, saved-penalty goalkeeper, save
  goalkeeper, and save shooter is inside the exact half-open Stage-7 interval at event time.
- Goalkeepers alone receive goalkeeper save events. Saved penalties link one on-pitch taker, one
  defending goalkeeper, and one compatible shot; missed/saved penalties add no goal.
- Every scored penalty links exactly one penalty event to exactly one existing penalty goal.
  Assisters differ from scorers.
- All Stage-9 component values and totals are integers, and each total equals the exact component
  sum. BPS/bonus is calculated by the canonical rules engine over the complete scenario.
- The joint matrix rows equal the raw scenario player totals. Re-aggregating its normalized
  weights reproduces every player summary PMF without changing the underlying matrix.
- Football outcomes produce more than one player-points row. Repeating the identical request and
  root seed produces an identical validated result and semantic result hash.
- Manual/transient and donor-private limitations remain in every scenario/result warning set.
  Reconstructing the request in `PRODUCTION` mode is rejected by the public request contract.

This proves engineering integration only. It does not accept the port or activate production.
