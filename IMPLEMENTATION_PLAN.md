# DMF Pulse Stage 9 — PTS-009 implementation plan

## Objective

Implement the bounded DMFP-19 Stage 9 vertical slice on
`stage/A9/PTS-009-fpl-points-simulation`, based on accepted parent
`9d7c360ab6a4cc7bfc6d6f41e44be6b47512b272`. Accepted Stage 7 participation
and Stage 8 joint-score uncertainty are transformed into coherent scenario-level
player events, exact rules-driven FPL points, joint BPS/bonus outcomes, player
distributions, Gameweek matrices, and Monte Carlo diagnostics.

This plan does not authorize Stage 10 manager-state or optimisation behavior,
target-season rules changes, a database migration, a merge, or self-acceptance.

## Integrated design

1. `upstream.py` validates the accepted `MinutesPredictionResult`,
   `TeamMinutesProjection`, `Stage7MinutesContext`, and `JointScoreDistribution`
   contracts without aliases or binary-float conversion of Stage 8 probabilities.
2. `allocation.py` implements the explicit TEMP-EVT-002 model. Every sampled team
   goal is represented exactly once as a scorer goal or opponent own goal, with
   coherent goal mechanism, assist classification, timing, team, and player vectors.
3. `rules_adapter.py` converts event vectors to accepted
   `dmf_pulse.rules.models.FixtureScenario` inputs and delegates scoring, BPS, tie
   ranking, and bonus allocation to the accepted rules engine.
4. `service.py` samples the exact Stage 8 matrix and Stage 7 participation paths,
   allocates events using deterministic named streams, retains upstream identities,
   and fails closed for fixture/ruleset blockers.
5. `summaries.py` produces weighted PMFs, moments, quantiles, thresholds,
   component covariance, BPS/bonus diagnostics, and the complete integer
   player-by-scenario matrix with dependence summaries.
6. `gameweek.py` and `gameweek_summaries.py` assemble blank, single-fixture, and
   shared-draw multiple-fixture outputs. Multiple-fixture output explicitly records
   the absence of sequential readiness transitions.
7. `monte_carlo.py` separates numerical diagnostics—ESS, MCSE, threshold standard
   error, quantile batch stability, and stopping state—from football uncertainty.
8. `artifacts.py` and the `dmf fpl-points` CLI publish and validate canonical JSON
   with an embedded semantic hash and detached SHA-256.

## Dependency and RNG decision

NumPy was removed. `seed.py` derives named seeds with SHA-256 and uses the Python
standard library MT19937 implementation behind the versioned identity
`python-mt19937-pts-v1`. Sampling, shuffling, Poisson, binomial, and exact
integer-weight selection are implemented in the bounded module. Scenario identity
depends on root seed and semantic namespace, not batching or worker order. No runtime
or development dependency changed.

## Delivery sequence

1. Verify archive, branch, parent, remote, and clean initial worktree.
2. Overlay only declared candidate files and manually reconcile CLI registration.
3. Reconcile final accepted Stage 7/8 contracts at the narrow adapter boundary.
4. Replace the generated reference oracle with the accepted compiled-rules adapter.
5. Harden event, artifact, coverage, resource, and scope contracts with mutation tests.
6. Run focused Stage 9 and directly inherited Stage 2/7/8 tests.
7. Run formatting, lint, strict typing, resource regeneration, CLI, and artifact gates.
8. Exercise the single-head migration matrix and PostgreSQL integration on a
   disposable PostgreSQL 18.4 service.
9. Run one final repository coverage regression after the product/test tree is fixed;
   measure the wall-clock performance gate separately from coverage instrumentation.
10. Build and independently verify the installed wheel outside the checkout, refresh
    the repository snapshot, validate the repository, and scan for secrets.
11. Create exactly one commit, push the required branch, and leave merge/review and
    acceptance to a separate reviewer.

## Completion boundary

Implementation is complete only when every gate above passes on the final tracked
tree. Production 2026/27 use remains independently blocked until the target ruleset
is verified, approved, production eligible, and ACTIVE.
