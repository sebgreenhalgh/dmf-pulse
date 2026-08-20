# GW1 Checkpoint 2.3 - current football-event validation

## Scope and identity

- Canonical branch - `readiness/GW1-2026-27-live-input-initial-squad`.
- Immutable programme parent - `9eb57143f6ee92f67c78607cc386678d962e62d4`.
- Starting accepted remote SHA - `4899a1a9b31532600676f280a62599078eab5763`.
- Capability commit - `008ad0d2369d89da0beff120920253eb315e9251`.
- Dedicated Linux workflow - run `32325586142` (`PASS`), job `96296054494`,
  exact head `008ad0d2369d89da0beff120920253eb315e9251`.
- Real credentialled provider call - `OPERATOR_CHECKPOINT`.
- Accepted current score/player prior artifact - `NOT_SUPPLIED / OPERATOR_BLOCKER`.

## Implemented vertical slice

- The Checkpoint-2.2 transient handoff now retains the accepted Stage-7
  sampler's exact 256 coherent lineup paths and both conditional minute PMFs
  per player. These inputs are hash-bound, independently reconstructed and
  never persisted.
- `GW1_CURRENT_FOOTBALL_EVENT_REVIEW` binds every current fixture's exact
  orientation, kickoff, Stage-6 market result, Stage-7 team/player identities
  and complete player universe into a deterministic private review hash.
- A current run requires one immutable governance-accepted
  `ACCEPTED_MODEL_ARTIFACT`,
  accepted before the event decision time and valid through every kickoff. It
  must exactly cover all fixtures and players with score priors plus complete
  TEMP-EVT-002/TEMP-PTS-001 allocation inputs. The adapter has no path that
  estimates rates from H2H alone or substitutes the packaged synthetic example.
- Every fixture runs through the existing `ScoreDistributionService`. The
  output is its exact coherent joint score matrix, including market residuals,
  goals-conceded equality, clean sheets, BTTS, 1X2 views, Stage-7 identity and
  immutable policy/prior/input hashes.
- Coherent Stage-7 lineup paths are paired across the fixture and conditional
  minutes are sampled with deterministic named seeds. The original Stage-7
  PMFs remain unchanged. Bench-role mass at 90 minutes is explicitly
  conditioned to the Stage-9-representable 0-89 support and recorded as a
  material degradation.
- The output carries the exact Stage-9 input primitives: score distribution,
  256 complete participation paths, allocation profiles and allocation config.
  Player goal/assist/event allocation remains unexecuted until the accepted
  Stage-9 operation in Checkpoint 2.4; no parallel simulator is introduced.
- One deterministic transient Gameweek identity is shared across fixtures.
  Checkpoint 2.4 must additionally bind one common Stage-9 root seed and prove
  the accepted Gameweek assembly's shared outcome-draw behavior.
- Official-FPL raw and derived retention remain denied. The adapter performs no
  filesystem write, database access or provider call. Its safe summary exposes
  only counts, confidence grades and semantic identities.

## Authority finding and operational blocker

- The repository contains no accepted current-season team-strength/count-prior
  artifact and no accepted current player allocation/rate artifact.
- The approved live market foundation contains full-time 1X2 (`h2h`) only.
  The accepted specification permits fitting score rates from 1X2 plus a total,
  but not from 1X2 alone. A handcrafted or synthetic rate would therefore be an
  unapproved substitution.
- Engineering acceptance can prove the guarded integration with synthetic
  contract fixtures. It cannot claim a real current projection. The operator
  path remains fail-closed until a governance-accepted artifact is supplied
  in the same transient run.

## Hostile review

### P0/P1 remediated

1. Stage-7 exposed only public marginals while Stage 9 requires coherent paths.
   The existing accepted sampler outputs are now retained and hash-bound; no
   independent lineup reconstruction is used.
2. Current H2H could be mistaken for a complete Poisson prior. The new boundary
   requires explicit accepted rates and rejects missing, synthetic, partial,
   mismatched, expired and post-cutoff artifacts.
3. Player allocation could silently use the repository's illustrative
   TEST/REPLAY YAML. Current artifacts must use the accepted temporary source
   tags and supply complete player profiles; `TEST_SYNTHETIC` is rejected.
4. Generating player events in both Stages 8 and 9 would break deterministic
   lineage. Checkpoint 2.3 produces exact Stage-9 input primitives, proves they
   satisfy the strict request contract in tests, and records
   `STAGE9_REQUEST_READY_NOT_EXECUTED`; only Stage 9 will allocate and score.
5. Player identities alone did not prove that allocation profiles retained the
   reviewed home/away team assignment. The review now binds separate team
   player universes, the handoff rechecks profile-to-participant teams, and a
   cross-team swap attack fails closed.

### Material limitations retained

- Stage-7 is still an empty-current-history cold start trained on the frozen
  synthetic TEST/REPLAY contract dataset.
- No production calibration claim is made for score, minutes or allocation
  inputs.
- Bench-role minute-90 mass is not representable by the accepted Stage-9
  interval contract and is transparently conditioned out of sampled paths.
- The real current prior artifact has not been supplied, so no current player
  table, points distribution or recommendation exists.

## Local validation

- New current-event tests - `12 passed`.
- Combined current Stage-7/event adapter tests - `25 passed`.
- Branch-aware coverage - `92%` total (`741` statements, `146` branches),
  above the required `90%`; current availability measured `93%` and the current
  event adapter measured `90%`.
- Final-tree accepted Stage-6 through Stage-9 unit/property/contract regression
  command - `493 passed`.
- Disposable PostgreSQL 18.4 migration plus Stage-7/8/9 integration command -
  `46 passed`; the named container was stopped and auto-removed. An initial
  local invocation omitted `DMF_ENVIRONMENT=TEST`, producing `45 passed, 1
  skipped`; it was corrected and is not represented as the acceptance result.
- Ruff format - `PASS`, `514 files`; Ruff lint - `PASS`.
- Strict mypy - `PASS`, `196 source files`.
- Source/wheel build - `PASS`, `dmf-pulse 0.2.0`.
- Isolated installed-wheel import of the new public bundle and review builder -
  `PASS` outside the project environment.
- First-party secret scan - `PASS`, `finding_count=0`.
- Workflow YAML parse and `git diff --check` - `PASS` before capability freeze.
- Repository validation - `NOT_EXECUTED` at this bounded checkpoint. The known
  branch-wide stale GCS-008 current-manifest debt remains reserved for final
  engineering acceptance and is not promoted to PASS.

## Status

- Local bounded engineering result - `PASS`.
- Linux engineering result - `PASS`.
- Checkpoint 2.3 engineering capability - `COMPLETE`.
- Current operator projection - `BLOCKED_CURRENT_EVENT_PRIOR_ARTIFACT`.
- PR, merge and production activation - `NOT_AUTHORIZED / NOT_PERFORMED`.

## Linux and remote validation

- Dedicated run `32325586142` passed on exact capability commit
  `008ad0d2369d89da0beff120920253eb315e9251`; job `96296054494` passed every
  step and stopped its PostgreSQL service cleanly.
- Frozen sync and PostgreSQL migration passed.
- The accepted Stage-6 through Stage-9 regression command passed `493` tests.
- Current-adapter branch coverage passed `25` tests and the configured `90%`
  gate at `91.77%` (`741` statements, `146` branches).
- PostgreSQL Stage-7/8/9 integration passed `46` tests.
- Ruff reported `514` files formatted and no lint findings; strict mypy passed
  `196` source files; wheel/sdist build, secret scan (`finding_count=0`) and
  commit whitespace assurance passed.
- After the successful run, the canonical branch was fetched. Local HEAD and
  `origin/readiness/GW1-2026-27-live-input-initial-squad` were exactly equal at
  `008ad0d2369d89da0beff120920253eb315e9251` before this evidence-only
  attestation.

## Capability file hashes before commit

- `src/dmf_pulse/availability/current.py` -
  `1e6ced50584058bae0657db6926e4d783794fc977c561bf9e1f885a55280b003`.
- `src/dmf_pulse/fpl_points/current.py` -
  `3dfd63fd8ec82f885734077ffa69808ea73a04841de7d1bc45d7f07b95b24282`.
- `src/dmf_pulse/fpl_points/__init__.py` -
  `d7b9f5a5d762303f028f98ac9359dad1bf2b6b183e3284c57a7d1400e2365f47`.
- `tests/unit/fpl_points/test_current_football_events.py` -
  `fa02957834d3a7202367cac8750ec7dfbf7f4164e23deccdb1897862fd8b28d2`.
- `.github/workflows/gw1-checkpoint-2-3-validation.yml` -
  `af2fff322935892fc21d83a1da6579edc2a9e1d848a1661e5c24697cc7c0afd5`.
