# Stage 9 final upstream contract map

## Accepted lineage

- Stage 9 parent / accepted Stage 8 merge: `9d7c360ab6a4cc7bfc6d6f41e44be6b47512b272`
- Final accepted GCS-008 implementation lineage: `69b665315ab20b8ac13a38fafed7b5c64ff7e7ce`
- The provisional candidate assumption at `668662a1c9a3f3a92d1c0305e6dfbf6b1d32a07a`
  was discarded during integration.

## Stage 2 — accepted rules transform

`AcceptedRulesAdapter` consumes `CompiledRuleset` and an optional matching
`ApprovalRecord`, converts Stage 9 event vectors to accepted `PlayerScenario` and
`FixtureScenario` values, and calls `score_fixture`. Stage 9 reads the returned exact
integer components, BPS, bonus, and total. It does not define FPL point weights, BPS
values, clean-sheet thresholds, defensive-contribution policy, or bonus tie rules.

Accepted rules errors are translated to typed `FplPointsError` failures without
altering their fail-closed meaning.

## Stage 7 — availability/minutes contracts

The adapter accepts the actual public `MinutesPredictionResult` or
`TeamMinutesProjection` types from `dmf_pulse.availability`. A result must be
`PROJECTED` and contain its immutable projection; blocked results are rejected.

The final team projections provide fixture/team/as-of identity, model and dataset
hashes, result/scenario-set hashes, and per-player `projection_sha256` identities.
`Stage7MinutesContext.from_projections(home, away)` is used to derive the same
semantic context Stage 8 binds. Stage 9 records a one-to-one player projection hash
map for the complete participant universe.

Stage 7 intentionally exposes no public coherent on-pitch path object. Therefore the
Stage 9 request supplies explicit sampled path rows (`player_id`, `team_id`, FPL
position, official minutes, entry/exit interval, starter, and hard-ineligible state),
while all projection identities come from the accepted Stage 7 models. Positive
minutes require a half-open interval; zero-minute or hard-ineligible players cannot
receive events.

The frozen reference request binds Stage 7 context semantic SHA-256
`d5af65b3be0bc6ca02759953b2599cf8a98c2ad198c83e4aa230c726a89d20c2`.

## Stage 8 — final GCS-008 contract

`FixtureSimulationRequest.score_distribution` is the actual final
`dmf_pulse.football_events.JointScoreDistribution`, not a Stage 9 copy. The adapter
accepts that model or validates a mapping directly into it. It does not accept the
candidate's provisional `cells`/`scoreline_cells` aliases.

The canonical `probabilities[home_goals][away_goals]` matrix is retained as exact
12-place decimal strings. Stage 9 verifies matrix semantics through the accepted
model and samples using integer weights on a 10^12 denominator; no lossy float matrix
is introduced. It also retains the full Stage 8 object in successful output.

The request enforces:

- exact fixture/home/away identity;
- Stage 8 `as_of` = Stage 8 `information_cutoff` = Stage 9 cutoff;
- Stage 7 context semantic hash = Stage 8 `source_minutes_context_sha256`;
- complete player projection hash coverage;
- accepted Stage 8 semantic/result hash validation and confidence/degradation fields.

The frozen Stage 8 reference distribution has result SHA-256
`31d41317c0cf06002edd8e8fb47c4702706661f2227304182e3c4b8995e06b7e`.

## Reconciliation result

All provisional Stage 8 aliases, invented ruleset fields, model/policy lineage names,
and binary-float probability paths were removed. No Stage 7/8 mathematics or public
models were copied. Compatibility coverage exercises the accepted Stage 7 and final
Stage 8 packages directly.
