# D7 offline acceptance

## Capacity and exactness

- The immutable L7 record is classified as `POLICY_GENERATION_LIMIT`: Stage 8
  completed 30/30 fixtures, Stage 9 assembled 3/3 Gameweeks, MC passed 3/3,
  deterministic discovery completed at 783,057 cumulative legal actions, and
  generated-policy work first crossed the 786,432 cap at 786,433. The backend
  returned no incumbent and the shadow world never started.
- Complete repository-owned baseline-like demand was 1,432,370 generated policies
  and 1,432,370 legal actions. Shifted-shadow-like demand was 1,432,641 generated
  policies and 1,432,370 legal actions.
- The 10,000,000 values were offline discovery ceilings only. Governed v2 limits are
  2,097,152 generated policies, 786,432 retained Pareto candidates, and 2,097,152
  cumulative legal actions.
- Governed and 10-million runs had identical recommendation, no-transfer baseline,
  root counterfactual, complete transfer-count frontier, future policy and objective
  utilities in both projection orderings.
- The lossless incremental Pareto implementation still evaluates and counts every
  logical policy. Peak temporary populations were 1,032 and 1,271 rather than the
  complete generated families. Discovery retains legal actions but replays rather
  than retains heavyweight transitions. The completed baseline-high process had a
  reviewer-observed Windows `PeakWorkingSet64` of 1,827,266,560 bytes; this is
  platform-local context, not a portable governed metric.

## Test populations

- Complete public optimisation population: 334 passed in 580.92 seconds.
- D1-D7/team-strength, five-case, private rolling and one-command selection:
  476 passed, 179 deselected in 2,881.55 seconds.
- Direct Stage 8/9/10 population: 502 passed in 89.07 seconds.
- Final D7 policy/evidence/diagnostic population: 15 passed in 87.92 seconds.
- Governed Stage-11 golden and independent-oracle population: 48 passed in 86.08
  seconds. The D7 result-envelope extension intentionally changed 20 authenticated
  result hashes; statuses, actions, objectives and oracle semantics remained green.
- Earlier focused checkpoints: 80 passed, 9 passed, 27 passed and 4 passed.
- Mandatory full-repository branch coverage, performance and PostgreSQL populations
  are supplied by exact-SHA CI; no coverage threshold or exclusion changed.

## Quality and packaging

- Frozen dependency sync: PASS, 40 packages checked.
- Ruff format and check: PASS.
- Strict mypy: PASS, 315 specified source files.
- Wheel and source distribution: PASS.
- Clean external runtime-only installed-wheel verification: PASS; L1-L7 consumed,
  no L8 authority, provider calls zero, mutable source rejected, and wrong purpose
  blocked before providers.
- Repository validator, canonical manifest, first-party secret scan and capped review
  pack are generated after the final review record is sealed.
- `git diff --check`: PASS.

## Boundaries

- Official FPL requests: 0.
- The Odds API requests: 0.
- Live OpenFootball requests: 0.
- Credential inspection: none.
- Historical private player, squad, price or fixture rows reconstructed: none.
- Candidate scope, transfer scope, exactness, D6 baseline reuse and the shared
  deterministic fast-path selector remain unchanged.
- L1 through L7 are permanently consumed. No L8 authority exists. Team strength
  remains `SHADOW_NOT_MODEL_INPUT`; production activation is false.
