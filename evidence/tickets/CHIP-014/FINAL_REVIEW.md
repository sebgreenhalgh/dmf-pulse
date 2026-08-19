# CHIP-014 final independent review evidence

- Evidence date: `2026-08-20`
- Reviewed implementation checkpoint: `f8511b2ae3b3868501b427e82f55a23dc74ad4c0`
- Immutable original parent: `a8796d4edacea4c87ee6461d381f4df87e1ef39c`
- Actual starting remote SHA: `853142c84b909f1f22b6e31b657b21d990c331b1`
- Checkpoint 14.07 capability: `6583a0d8c7a69a07668cbd53db99b9119a7f89d5`
- Verdict supported by this evidence: `PASS_WITH_NONBLOCKING_LIMITATIONS`

## INDEPENDENT_REVIEW_FINDINGS

### P0

None found. Executable recommendations retain cutoff-safe Stage 12 lineage; perfect-information
output remains diagnostic; sequential replay executes only the frozen root action.

### P1 — all closed

1. A self-consistent compiled bundle could rely on its own sealed status/capabilities without an
   independent compile. The validator now recompiles every definition, checks compiler version,
   and the shared service invokes that validation.
2. A self-sealed inventory could alter minted tokens or concurrency without proving a legal state
   history. `validate_chip_inventory` now rebuilds from the bundle and replays selected, cancelled
   and activated transitions before exact comparison. Service and CLI share this path.
3. The pending-cancellable activation path bypassed effect/window/exclusion/current-selection
   checks. Activation now applies the complete legality contract to pending selections.
4. The service required a full chip-domain scenario hash to equal the scheduler identity hash,
   making real TC/BB/FH/WC evidence impossible to compose. It now binds the exact ordered
   scenario/draw/weight signature and reconciles current scheduler gross vectors to the attached
   domain evaluation.

### P2 — all material items closed

1. `exact_small_schedule_oracle` called production `_exact_search`. It is now an independent
   power-set enumerator with separate token, prefix, overlap/concurrency, gap and value checks; a
   regression proves it still works when production search is patched to fail.
2. Windows CRLF sidecar handling, deterministic frozenset serialisation, Python 3.13 typing and
   Stage 14 Ruff-format/lint debt were corrected.
3. External-payload guard coverage was expanded across CLI, service models, artifacts and replay,
   raising true raw branch coverage above the required threshold.
4. Secret-scan false positives for the FPL domain term “chip inventory token” received only exact
   path-and-fingerprint allowances with explicit non-secret rationales.

### P3 / deferred challengers

- Prospectively evaluate chip-policy quality when target-season history exists.
- Replace or validate the transparent V1 continuation approximation under a future approved
  DMFP-20 decision.
- Activate Stage 13 price paths only after rights and target-season calibration gates pass.

## COMMAND_LEDGER

The literal ledger is retained in `COMMAND_LEDGER.txt`. Commands were run from the repository root
with no source-tree `PYTHONPATH` used for installed-wheel acceptance.

## TEST_RESULTS

- Final Stage 14 matrix: `405 passed in 12.96s`.
- Stage 14 adversarial raw-branch run: `405 passed in 22.76s` under coverage.
- Targeted inherited regression matrix: `127 passed in 84.05s`.
- Single complete-repository attempt: `2579 passed, 1 skipped, 2 failed, 205 errors in 1618.17s`.
  All 205 errors were PostgreSQL setup failures because `DMF_TEST_DATABASE_URL` was absent. The
  generic wheel verifier failed for the same missing variable; the second failure was the stale
  active repository manifest, subsequently refreshed. The full run is not called PASS.

## VALIDATION_STATUS

- Stage 14, inherited regressions, frozen sync, Ruff, mypy, build, secret scan and external-wheel
  Stage 14 CLI acceptance pass.
- Repository validation is refreshed after final deliverable changes and recorded by its generated
  report; no stale-manifest PASS is asserted here.
- The complete PostgreSQL-backed repository matrix remains environment-limited.

## COVERAGE

Coverage definition: raw branch-only numerator divided by raw branch opportunities from
coverage.py JSON, not the combined line+branch percentage.

- Aggregate: `1142 / 1268 = 90.063091%` raw branch coverage.
- Combined line+branch metric, reported only for clarity: `94.818976%`.
- `compiler.py`: `35 / 38 = 92.105263%`.
- `inventory.py`: `92 / 108 = 85.185185%`.
- `captaincy.py`: `69 / 70 = 98.571429%`.
- `bench_boost.py`: `54 / 58 = 93.103448%`.
- `free_hit.py`: `47 / 54 = 87.037037%`.
- `wildcard.py`: `81 / 86 = 94.186047%`.
- `scheduler.py`: `169 / 178 = 94.943820%`.
- `schedule_models.py`: `146 / 154 = 94.805195%`.
- `service.py`: `45 / 54 = 83.333333%`.
- `replay.py`: `58 / 62 = 93.548387%`.
- `cli/chips.py`: `25 / 30 = 83.333333%`.

The aggregate gate is required to be at least 90%; no claim is made that every module individually
exceeds 90%.

## TARGETED_REGRESSION_SCOPE

Exact nodes and rationale:

- Rules: `tests/unit/rules/test_2026_27_verification_gate.py`,
  `tests/unit/rules/test_yaml_and_compiler.py`,
  `tests/contract/rules/test_2026_27_full_season_readiness.py` — accepted target rules,
  compilation and activation boundaries.
- Stage 9: `tests/unit/fpl_points/test_summaries_and_mc.py`,
  `tests/contract/fpl_points/test_upstream_contracts.py` — joint scenario/points identity.
- Stage 10: `tests/unit/optimisation/test_r2b_semantics.py` — tactical/autosub scoring semantics.
- Stage 11: `tests/unit/optimisation/test_multi_gameweek_state.py`,
  `tests/contract/optimisation/test_stage11_integration.py` — manager state and transfer lineage.
- Stage 12: `tests/unit/evaluation/test_leakage.py`,
  `tests/replay/evaluation/test_policy_replay.py`,
  `tests/unit/evaluation/test_regret_reports_artifacts.py` — cutoff, replay and artifact contracts.
- Stage 13: `tests/unit/prices/test_paths_selling.py`,
  `tests/integration/prices/test_current_rules_integration.py` — selling value, status and current
  rules integration.

Result: `127 passed`.

## STATIC_ANALYSIS_STATUS

- `uv run ruff format --check .`: PASS, 582 files already formatted.
- `uv run ruff check .`: PASS.
- `uv run mypy src/dmf_pulse`: PASS, 226 source files.
- `git diff --check`: PASS at each publication checkpoint and final preparation.

## BUILD_WHEEL_RESULT

- Canonical `uv build`: PASS; produced `dmf_pulse-0.2.0.tar.gz` and
  `dmf_pulse-0.2.0-py3-none-any.whl` through Hatchling.
- A new environment under the system temporary directory installed the wheel offline with
  `PYTHONPATH` cleared and ran the Stage 14 CLI successfully.
- The generic `scripts/verify_wheel.py` repository verifier requires
  `DMF_TEST_DATABASE_URL` and therefore reported that environment prerequisite as unavailable.

## CLI_ACCEPTANCE

Installed wheel commands passed: `dmf --version`, `dmf chips --help`, `validate-rules`, `validate`,
`schedule`, `compare`, and `triple-captain-value`. Outputs were substantive canonical JSON (the
schedule was 58,179 bytes and decision set 67,184 bytes), not placeholder success.

## CHIP_RULE_ASSURANCE

Stage 14 consumes compiled accepted rule definitions for availability, inventory, windows, expiry,
effects, duration, concurrency and gaps. The validator independently recompiles definitions. The
2026/27 manifest is VERIFIED but not ACTIVE, so installed capability remains
`ENGINEERING_READY_PENDING_TARGET_RULES` and `production_eligible=false`.

## CAPTAIN_VICE_ASSURANCE

Captain and vice are jointly optimised on common scenarios with captain appearance, vice fallback,
both absent, correlated absence, postponement and DGW-partial behavior retained in domain tests.

## TRIPLE_CAPTAIN_ASSURANCE

Triple Captain is incremental effective-captain value under the compiled multiplier, including
zero-extra and alternative joint captain/vice cases; no DGW requirement is assumed.

## BENCH_BOOST_ASSURANCE

Bench Boost compares the chip policy to the best ordinary tactical policy and accounts for
autosub overlap, goalkeeper, appearance, preparation/hit/budget/future-XI/unwind costs, and measured
natural/engineered/Wildcard synergy.

## FREE_HIT_ASSURANCE

Free Hit compares the best temporary policy with the best normal transfer policy and proves exact
permanent squad, bank, free-transfer and purchase-spell restoration without temporary ownership
contamination.

## WILDCARD_ASSURANCE

Wildcard evaluates immediate, delayed, bridge and hold routes over multiple Gameweeks, with
permanent ownership spells, selling value, information, flexibility, expiry and other-chip
interactions. No fixed “bad players” heuristic is used.

## SCHEDULE_ORACLE_ASSURANCE

The tiny-instance oracle is independent of production search and enumerates every subset within its
declared bound. Property/golden tests compare the production optimum to that oracle and cover HOLD,
expiry, multiple copies, duration, gaps, deterministic ties and prefix-sensitive state.

## NONANTICIPATIVITY_ASSURANCE

Executable scheduling uses one common cutoff-safe scenario universe and root action. The
perfect-information schedule is labelled an upper-bound diagnostic and is never executable.

## STAGE12_REPLAY_ASSURANCE

Replay follows forecast → freeze/seal → execute current root only → transition inventory → reveal
eligible information → re-solve. A canary proves future information changes only the later action
while the earlier frozen decision hash remains unchanged.

## ARTIFACT_ASSURANCE

Content-addressed artifacts retain manager/rules/definition/inventory/scenario/price/continuation/
cutoff/code/seed lineage. Independent recomputation rejects action, schedule, rules, inventory,
scenario, cutoff, model/configuration, diagnostics and nested-envelope tampering.

## DEPENDENCY_REVIEW

Stage 14 added no dependency and did not change `uv.lock`. It uses existing Pydantic, Typer and
PyYAML/runtime infrastructure; no model/solver/network/provider/database dependency was introduced
for Stage 14.

## SCOPE_ASSURANCE

The immutable-parent diff contains Stage 14 compiler/inventory, captaincy/TC, BB, FH, WC,
scheduler, service/replay/artifacts/CLI, fixtures/tests/evidence and required CLI registration only.
No Stage 15 rank, effective ownership, rival, target-rank or differential objective was found.
Recovery transport/workflows and `recovery/` are absent.

## SECRET_SCAN

First-party scan: PASS with `finding_count=0`. New allowances are exact rule/fingerprint/path
tuples for reviewed FPL chip-inventory token terminology; no credential values were added.

## KNOWN_LIMITATIONS

- Target-season rules are VERIFIED, not ACTIVE/human approved.
- V1 continuation value is transparent and provisional.
- Stage 13 price paths remain rights-gated and target-season uncalibrated.
- Prospective target-season chip-policy performance is not yet established.
- The broad PostgreSQL/generic-wheel matrix needs an authorised `DMF_TEST_DATABASE_URL`.
- Human acceptance and merge remain pending.
