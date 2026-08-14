# Stage 9 assumptions and deviations

## Authority and boundary

Accepted repository contracts and DMFP-20 decisions control. DMFP-19 bounds this
delivery to PTS-009 items 19.09.01–19.09.06; broader DMFP-09 architecture remains
future work.

## TEMP-EVT-002 allocation baseline

- Team totals come only from the sampled final Stage 8 score matrix.
- Every goal is assigned exactly once to an eligible on-pitch scorer or an opponent
  own-goal player; scorer/team/mechanism and all player event vectors reconcile.
- For schema-v1.0 compatibility, legacy TEMP-EVT-002 ambiguity controls retain their
  historical modelling scope. For target schema-v1.1 exact PLAYER_POINTS scoring,
  allocation samples only replayable goal-chain facts and the compiled rules classifier
  resolves each evaluated candidate to a definite assist/no-assist result; raw model
  ambiguity never supplies final FPL eligibility. A scorer never assists the same goal.
- Goal time, cards, goalkeeper saves, an extra penalty path, and defensive actions are
  sampled only inside valid participation.
- Goal/assist/player shares are transparent model inputs, not FPL rule constants.
- The baseline is deterministic under root seed, scenario index, and named subsystem
  stream. It is not production player-prop calibration.

### Non-GK save-generation limitation (nonblocking)

The 2026/27 scoring and Stage-9 event contract correctly allow an outfield FPL-position
player temporarily keeping goal to receive save points. TEMP-EVT-002 ordinary-save
sampling still uses the participant's FPL `GK` position and therefore does not generate
that temporary-role case. This is an explicit nonblocking generator limitation; no
Stage-7 role/state model is introduced here merely to synthesize it.

## TEMP-PTS-001 auxiliary BPS baseline

- Auxiliary passes, recoveries, shots, fouls, chances, dribbles, crosses, and related
  actions are separately tagged and reported with completeness/degradation state.
- Goals, assists, saves, penalties, cards, and other event-linked actions are not
  regenerated as residual events.
- Auxiliary successful-tackle BPS is zero because defensive tackles are generated in
  the defensive-action vector, avoiding a known double count until a verified event
  taxonomy replaces the baseline.
- This is not a production-grade BPS residual model.

## Numerical and dependency decisions

- NumPy was removed; no dependency or lock change was required.
- Named seed derivation uses SHA-256 and versioned standard-library MT19937 streams
  (`python-mt19937-pts-v1`).
- The Stage 8 12-place matrix is sampled with exact integer weights on a 10^12
  denominator. Binary float is not used to reinterpret upstream probabilities.
- Scenario points and BPS are strict integers. Float values are limited to simulation
  weights and statistical summaries.
- Quantiles use the weighted discrete inverse CDF. Correlation is null with an
  explicit reason when either variance is zero.
- Canonical JSON was chosen instead of Parquet to avoid an unapproved runtime
  dependency and persistence expansion. The full matrix is still retained.

## Multiple-fixture approximation

Blank Gameweeks are exact zero point masses. Single-fixture Gameweeks preserve their
fixture scenarios. Multiple-fixture assembly shares deterministic draw identity and
sums player fixture components exactly, but does not apply sequential injury,
dismissal, suspension, fatigue, or readiness transitions. Output records
`NO_SEQUENTIAL_CROSS_FIXTURE_TRANSITION` and degraded confidence.

## Deliberate exclusions

There is no migration and no manager-state, optimiser, captaincy, chip, autosub,
transfer-hit, price, effective-ownership, or rank-strategy code. There is no advanced
prop reconciliation, full shot/xG tree, or production BPS residual model.
