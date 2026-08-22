# DMF Pulse execution plans

## CI-GOV-001 required CI runtime budget

- Architectural main parent: immutable `baed47bce7a158d91afe38351a2c65be60444adf`.
- Stacked technical parent: remote CI-FPL engineering head
  `652bae84fba9bdfbf435367d6140270fa8378d57`.
- Branch: `governance/CI-GOV-001-ci-runtime-budget` in a new isolated worktree.
- Classification: the corrected required suite exhausted the repository quality job's 35-minute
  execution budget during branch coverage; no test failure preceded termination.
- Owner-authorized change: only `.github/workflows/ci.yml` `timeout-minutes: 35` to `60`.
- Safety: retain every command, order, condition, PostgreSQL 18.4 image, test selection, coverage
  threshold, build/wheel gate, repository validator, and secret scan unchanged.

### CI-GOV-001 checkpoints

- [x] Verify immutable refs, PR #16, protected worktrees, and run `32598102993` timeout evidence.
- [x] Create the isolated stacked worktree from exact remote technical head `652bae84...`.
- [x] Freeze the ticket, acceptance boundary, plan, and bounded 60-minute owner authorization.
- [x] Prove the governance delta has zero product/test/config/migration/dependency change and only
  the intended timeout semantic change.
- [x] Pass local YAML/static/repository/security validation and refresh only the authorized current
  manifests required by canonical assurance.
- [ ] Push normally, wait for the complete 60-minute GitHub Actions result, and record every
  required step duration without rerunning or weakening a gate.
- [ ] Seal evidence and hand off for independent governance review; do not merge or modify PR #16.

## CI-FPL-REPLAY-001 deterministic synthetic FPL replay time

- Parent/branch: immutable `baed47bce7a158d91afe38351a2c65be60444adf` on
  `remediation/CI-FPL-REPLAY-001-deterministic-synthetic-time`.
- Classification: inherited main FPL replay-clock defect exposed by PR #16; the accepted
  LIVE-ODDS head `5e55cf3361a1abff4b2e32dcc30fe42900ea2e16` and PR remain immutable.
- Scope: one explicit frozen synthetic replay/resume time policy in FPL `service.py`, directly
  relevant TIME-01 through TIME-18 tests, ticket/evidence, and conditional active-manifest refresh.
- Safety: ordinary/manual/live processing stays bound to actual availability; no Odds, workflow,
  migration, dependency, rule, fixture-date, cutoff, rights, LIVE-ODDS, or PR #16 change.

### CI-FPL-REPLAY-001 checkpoints

- [x] Verify Git/PR identities, inherited A4 authority, remote migration-matrix pass, exact parent
  PostgreSQL failure, and controlled PRE/POST/`post_cutoff` reproduction.
- [x] Freeze the narrow ticket, acceptance matrix, root-cause record, and evidence plan.
- [x] Add TIME-01 through TIME-18 RED regressions and implement deterministic replay/resume time.
- [x] Pass the focused PostgreSQL 18.4 integration matrix, migration matrix, remaining blocked CI
  vertical slice, static analysis, and measured coverage thresholds.
- [ ] Pass final full/static/build/wheel/repository/security gates and branch GitHub Actions.
- [ ] Seal final evidence, commit/push the remediation branch, and hand off for independent review;
  do not merge or modify PR #16.

## CHIP-014 Stage-14 chip optimisation

- Ticket/stage: `CHIP-014`, DMFP-19 Stage 14; immutable original parent
  `a8796d4edacea4c87ee6461d381f4df87e1ef39c`; implementation branch
  `stage/A14/CHIP-014-chip-optimisation`.
- Resume boundary: checkpoints 14.01 through 14.06 are preserved on the canonical remote at
  `853142c84b909f1f22b6e31b657b21d990c331b1`; 14.07 service/replay/CLI/artifacts is absent and
  is the first unfinished capability.
- Scope: best-policy Free Hit comparison with exact permanent-state restoration; immediate,
  delayed and bridge Wildcard policies; transparent finite-inventory scheduling with an exact
  tiny-instance oracle and nonanticipativity; shared service/CLI, Stage-12 rolling replay and
  immutable evidence.
- Safety: current target-season rules are consumed from the compiled rules view; no duplicated
  chip constants, RL/MCTS/black-box continuation, open-loop future execution, merge, tag or human
  acceptance. A draft PR is permitted only after the independent review and all engineering gates.

### CHIP-014 checkpoints

- [x] Verify remote ancestry/progress and recover the exact Git workspace without restarting
  completed checkpoints.
- [x] Remediate the discovered generic vice-fallback compiler regression and publish it durably.
- [x] Complete and publish 14.04 Free Hit.
- [x] Complete and publish 14.05 Wildcard.
- [x] Complete and publish 14.06 scheduler/continuation.
- [x] Define tests/contracts for shared service models, cutoff-safe artifacts, sequential replay,
  probability lineage and the `dmf chips` installed-wheel surface.
- [x] Implement and publish 14.07 service/CLI/replay/evidence, then verify the remote product tree.
- [x] Independently review the complete immutable-parent Stage 14 diff; remediate all P0/P1 and
  material in-scope P2 findings with adversarial regressions.
- [x] Run focused coverage, inherited regressions, one bounded repository suite, static/build/
  wheel/installed-CLI and final assurance.
- [x] Remove all recovery-only workflows/material and verify the reviewed branch lineage.
- [x] Publish final evidence, verify local/remote equality, and open a draft
  PR to `main` without merging or marking human acceptance.

## PRC-013 Stage-13 price prediction and ACT/WAIT

- Ticket/stage: `PRC-013`, DMFP-19 Stage 13 / playbook B3; immutable parent
  `ce7fe8f4354d95a477afcf6eed45f63cf0ab772e` on `main`.
- Branch: `stage/A13/PRC-013-price-prediction`.
- Scope: immutable cutoff-safe price observations and update cycles; transfer-flow,
  ownership, status, calendar and recurrent features; deterministic P0 no-change,
  P1 regularized competing-logit and P2 recurrent latent-pressure baselines; calibrated
  next-update probabilities; recurrent 24h/72h/7d discrete price paths; exact Stage-11
  selling-value/scenario integration; Stage-12 chronological evaluation; complete
  ACT/WAIT utility; offline CLI and immutable artifacts.
- Safety: synthetic/replay and rights-approved inputs only; `usable_at` is the governing
  feature boundary; no hidden-threshold, wildcard, flag-lock, exact update-minute or weekly-cap
  claim; no predictor scraping; no new dependency, migration, Stage 14+ logic, live-history
  fabrication, PR, merge, accepted tag or production promotion.
- Model status: engineering implementation may become `IMPLEMENTED_PENDING_INDEPENDENT_REVIEW`;
  target-season use remains `SHADOW_ONLY`, `TARGET_SEASON_UNCALIBRATED` and rights-gated.

### PRC-013 checkpoints

- [x] Verify the immutable Stage-12 parent, advanced `main`, branch ancestry, repository
  authority and the complete external-research delta.
- [x] Freeze the ticket contract, model/dependency/rights boundary and focused acceptance plan.
- [x] Implement public contracts, temporal observations/cycles/features and the P0/P1/P2 ladder.
- [x] Implement recurrent price PMFs, Stage-11 selling/scenario reuse, Stage-12 evaluation and
  ACT/WAIT decision integration.
- [x] Add physical adversarial fixtures plus unit/property/contract/golden/integration/replay/CLI
  and artifact tests.
- [x] Run focused acceptance, targeted inherited regressions and >=90% Stage-13 branch coverage.
- [x] Run final Ruff, mypy, frozen sync, build, installed-wheel and CLI gates.
- [ ] Finalize truthful evidence, inspect the exact-parent diff, commit, push and verify remote
  equality; only then build and integrity-check the compact independent-Sol review bundle.

### PRC-013 independent Sol review and remediation

- Corrected pre-review baseline: `a2fdeea7b6514cb8f37b2f687d892998a1422973`; immutable
  parent remains `ce7fe8f4354d95a477afcf6eed45f63cf0ab772e`.
- [x] Verify the corrected GitHub lineage, complete Stage-13 tree and absence of recovery material.
- [x] Review repository authority, every Stage-13 production boundary and the complete baseline
  diff; classify P0/P1/P2/P3 findings independently.
- [x] Remediate every valid P0/P1 and material P2 with focused adversarial regressions.
- [x] Run the final Stage-13 coverage suite, inherited Stage-5/11/12/rules regressions and one
  complete repository pytest suite.
- [x] Run frozen sync, Ruff, strict mypy, build, clean installed-wheel CLI and assurance gates;
  update truthful independent-review evidence.
- [x] Commit remediation above the preserved implementation SHA, push normally, verify remote
  equality and create a draft PR to `main`; do not merge, accept or tag.

### PRC-013 final main integration

- [x] Verify reviewed/remote lineage and preserve
  `backup/stage13-pre-main-integration` at the independently reviewed HEAD.
- [x] Merge current `main` explicitly, retain both plan histories and reconcile Stage-13 price
  references with authoritative 2026/27 DMFP-02 mechanics and predictor evidence.
- [x] Pass the 116-test Stage-13 suite at >=90% coverage, the preserved 17 regressions and the
  104-test current-main dependency batch.
- [x] Make one bounded post-integration repository attempt and preserve `RESOURCE_LIMIT` without
  relabeling or rerunning it.
- [x] Pass frozen sync, Ruff, mypy, build, clean external-wheel rules/price CLI and assurance gates.
- [x] Commit the explicit integration, push normally, verify remote equality and update draft PR
  #12; do not merge, accept or tag.

## RUL-2026-27 independent full-ruleset review and remediation

- Repository/branch: `sebgreenhalgh/dmf-pulse`,
  `readiness/RUL-2026-27-full-season-activation`.
- Immutable parent: `4f1274ccef419a7c0bde335c48bd4070e248b2e6`.
- Pre-review branch HEAD: `56287412ec441af140b290e849428b15f0c7cd2d`;
  separately observed remote `main`: `ce7fe8f4354d95a477afcf6eed45f63cf0ab772e`.
- Scope: independently verify and remediate the complete 2026/27 rules-data,
  executable manager-state semantics, governance, activation gates, accepted
  Stage-1–11 consumers, tests, and final evidence. Do not incorporate Stage-12+
  modelling work, merge, activate production, or fabricate human approval.

### Independent-review checkpoints

- [x] Fetch and verify remote lineage; check out the dedicated branch without
  rebasing or merging later-stage work.
- [x] Resolve governing authority and freshly capture/compare official 2026/27
  rules, configuration, corrections, and representative-match availability.
- [x] Hostile-review rules data, compiler/runtime behavior, capabilities,
  approval/activation gates, consumers, tests, and temporary transport files.
- [x] Record severity-classified findings; fix every substantiated P0/P1 and
  reasonable in-scope P2 with focused adversarial/regression coverage.
- [x] Run repository-prescribed focused/full/static/PostgreSQL/build/wheel/
  repository/secret/diff gates and record non-executed gates truthfully.
- [x] Replace transient handoff material with final-code evidence, commit the
  complete remediation, push the same branch, and verify remote SHA equality.

Validation note: the exact repository-wide branch-coverage command reached a
30-minute cap without producing its JSON report. Focused rules/optimisation,
PostgreSQL, migration, static, package, repository, and secret gates passed; the
timeout is retained in `evidence/tickets/RUL-2026-27/VALIDATION_RESULTS.json`.
## OPT-010 - exact bounded one-Gameweek optimiser

- Ticket/stage: `OPT-010`, A10; immutable parent
  `a33f46cd7ec190fbd4959e2840527116f22547ac`; implementation branch
  `stage/A10/OPT-010-one-gameweek-optimiser`.
- Gate 0: frozen in `tickets/OPT-010/ticket.yaml`; implementation status `READY`.
- Scope: exact bounded `FIXED_SQUAD`, `PROVIDED_SQUADS` and preflight-bounded
  `BOUNDED_PLAYER_POOL` squad/XI/bench/captain/vice optimisation over accepted Stage-9 coherent
  scenarios.
- Safety: current production is fail-closed behind conservatively required `FULL_SEASON`;
  no Stage-9/rules-schema/dependency/migration change, heuristic, incumbent, manager state or
  Stage-11 behavior.

### OPT-010 checkpoints

- [x] Reconcile the provisional proposal against accepted Stage 9 and rules capabilities.
- [x] Resolve Gate 0 and freeze ticket, public contract, caps, tests and acceptance commands.
- [ ] Implement contracts/rules boundary/independent legality and exact tactical evaluation.
- [ ] Implement preflight-bounded search, oracle, service, hashes, artifacts and offline CLI.
- [ ] Run every literal acceptance gate and prepare capped independent-review evidence.

### OPT-010 R2 independent-review remediation

- Starting remediation head: `3f1550e3838e6f44c31990dcf83b2bc6ed7dc6fd`; immutable base remains
  `a33f46cd7ec190fbd4959e2840527116f22547ac`.
- [ ] R2A: bind the frozen public contract, accepted Stage-9 scenario lineage, and derived
  production capability/cutoff gates without changing Stage-9 or capability schemas.
- [ ] R2B: correct exact exhaustive search/tie/cap arithmetic, rules-owned autosub audit
  semantics, independent legality and Decimal-context determinism.
- [ ] R2C: harden immutable artifacts and make both offline CLI commands substantively verify
  hashes, lineage and legality.
- [ ] R2D: strengthen the independent oracle/adversarial proof, installed-wheel acceptance and
  final-head evidence; then run every frozen acceptance command.
- [ ] Obtain a fresh read-only Sol review. No self-acceptance, merge or PR-ready action.

## PTS-009 - bounded FPL-points simulation clean-checkout integration

- Ticket/stage: `PTS-009`, A9; required parent
  `9d7c360ab6a4cc7bfc6d6f41e44be6b47512b272` on
  `stage/A9/PTS-009-fpl-points-simulation`.
- Candidate: `dmf-pulse-stage9-candidate.zip`, 58 entries, SHA-256
  `d01bd3868dcecf5f5165680ec2c0a4a08a0fa18dedc0833f1223792cf72fe002`.
- Scope: implement only DMFP-19 items 19.09.01 through 19.09.06: coherent
  player-event allocation, exact rules-driven scenario scoring and joint BPS/bonus,
  weighted fixture/Gameweek distributions and joint matrices, Monte Carlo diagnostics,
  immutable offline artifacts, and the Stage-9 CLI.
- Final upstream authority: accepted Stage-8 merge parent `9d7c360...`, with GCS-008
  implementation lineage ending at `69b6653...`; consume its exact Decimal
  `JointScoreDistribution.probabilities`, `result_sha256`, policy/prior/input identities,
  cutoff, degradation and embedded `Stage7MinutesContext`. Consume accepted Stage-7
  team projection identities; do not invent per-player public projection-result identities.
- Constraints: preserve fail-closed target-season production rules behavior; reference
  rules are TEST/REPLAY only; no RUL-002 changes, migration, Stage-10+ manager-state or
  optimiser logic, hidden scoring constants, duplicated upstream mathematics, undeclared
  NumPy dependency, merge, PR, or self-acceptance.

### PTS-009 checkpoints

- [x] Apply the reviewed candidate overlay and manually reconcile the existing CLI.
- [x] Reconcile Stage-7/Stage-8 adapters and identities to the final accepted contracts.
- [x] Replace NumPy RNG/weighted-choice use with deterministic standard-library logic
  unless measured correctness/performance evidence proves a governed dependency is needed.
- [x] Pass focused unit/property/contract/golden/integration/performance suites and
  adversarial assurance mutations, including artifact identity and coverage fail-closed gates.
- [x] Pass relevant inherited Stage-2/7/8 compatibility, one final complete repository
  regression, Ruff, strict mypy, repository validation, secret scan, Alembic/PostgreSQL,
  wheel RECORD, and installed-wheel offline CLI gates.
- [x] Rebuild truthful manifests/evidence/docs from the final product tree and prepare
  the exact one-commit/push handoff; commit and remote SHA verification are terminal Git
  actions recorded outside this pre-commit execution plan.

## PTS-009 R3 - preserve red-card dismissal semantics without rewriting Stage-7 minutes

- [x] Confirm the corrective-ticket boundary at `fad2fc1fb2503e4de0d5db730fe2a763f2cbd12c`
  and review the accepted Stage-2/7/8/9 authority plus PTS-009 R2 closure evidence.
- [x] Add focused deterministic counterexamples for a 60-minute dismissed defender,
  post-dismissal conceded goals, the normal-substitution control, and Stage-7 90-minute
  authority.
- [x] Bind the internal dismissal endpoint to the selected Stage-7 interval endpoint only;
  do not alter intervals, effective endpoints, official minutes, or scoring rules.
- [x] Run the ticket's focused, Stage-9 deterministic, quality, and static-analysis checks;
  record the generated counterexample values. The Linux symlink-confinement probe is
  explicitly `NOT_EXECUTED` because this Windows host lacks symlink privilege.

## FPL 2026/27 rules launch verification

- Scope: independently verify every required `fpl-2026-27` rule family against
  current official 2026/27 FPL sources, compile and diff the captured artifact,
  and stop before human activation.
- Constraint: rules-data verification only; do not redesign the rules engine or
  silently carry 2025/26 values forward.

### Verification checkpoints

- [x] Resolve governing authority, clean worktree, target manifest, CLI, and
  focused rules assurance contracts.
- [x] Recheck the live official Help/Rules application, official 2026/27 launch
  announcements, and target-season bootstrap configuration.
- [x] Identify exact authoritative values and compare them with the 2025/26
  reference, including every published 2026/27 BPS change.
- [ ] Encode a production-eligible ruleset only after an approved schema/ADR can
  represent big-chance saves, split chip inventories/windows and effects,
  transfer transitions, selling-price rules, and per-rule provenance.
- [ ] Human approval and activation (explicitly outside this task).

### Verification decision log

- DMFP-02 section 27.5 requires an ADR/schema revision when a target-season rule
  cannot be expressed. The current schema cannot faithfully encode several
  verified 2026/27 rules, so the target remains fail-closed and the outcome is
  `BLOCKED_RULESET_VERIFICATION`, not a false `VERIFIED` artifact.

## MIN-007R7 + MIN-007H3 - final packaged replay and assurance remediation

- Ticket/stage: `MIN-007R7` then `MIN-007H3`, A7; required starting parent
  `d94410b0ddd9c6689226c10bebcf9dc52e7ca346` on
  `stage/A7/MIN-007-final-recovery`.
- R7 scope: package the frozen TEST/REPLAY availability resources, load them
  through `importlib.resources`, and prove the public 701 command from an
  isolated installed wheel without repository source-path access.
- H3 scope: make the acceptance ledger and final-evidence validators
  structurally and semantically fail closed, bind required gate artifacts,
  and measure network attempts at the exact installed-wheel public 701 CLI
  boundary.
- Constraints: preserve all frozen semantic identities, mathematical formulas,
  exact reachability waivers, Alembic revision `20260807_0006`, and the full
  stage range; no self-acceptance in this implementation conversation.

### MIN-007R7 + MIN-007H3 checkpoints

- [ ] Add synchronized packaged availability resources and public CLI loading.
- [ ] Prove isolated-wheel 701/alternate/709 behavior and create the exact R7 commit.
- [ ] Harden the assurance runner, validators, artifact bindings, and mutation tests.
- [ ] Run the complete assurance ledger, create the exact H3 commit, and rebuild the
  17-root review archive for a fresh independent reviewer.

## MIN-007R5F4 - final-output truthfulness and complete-only exact lookup

- Ticket/stage: `MIN-007R5F4`, A7; required parent `3867877d4c2d1c3febcdf4b456703e3356d9a8af`.
- Scope: close only the two AUDIT-007-3C P1s: derive and validate final-output
  identity from durable rows at the database boundary, and hide committed core
  drafts from every exact lookup.
- Constraints: harden unmerged migration `20260807_0006` without a new revision;
  preserve R5F1/R5F2/R5G/R5F3 freeze, numeric, provenance, and frozen-hash
  protections; no CLI/model/provider/network/MIN-007H work.

### MIN-007R5F4 checkpoints

- [x] Add database finalization reconstruction and direct-SQL truthfulness probes.
- [x] Require complete core state for exact/public prediction reads and cover aliases.
- [x] Run all 23 literal acceptance commands, record evidence, remove PostgreSQL,
  commit once, and verify a clean worktree.

## MIN-007R5F3 - freeze published graphs and bind evaluation provenance

- Ticket/stage: `MIN-007R5F3`, A7; required parent `f1d8a4a38b073e6ee4a259ee801a9273e5e207ce`.
- Scope: close the three AUDIT-007-3B P1 findings only: dataset lineage freeze, F-core/final-output lifecycle finalization, and strict evaluation provenance binding.
- Constraints: preserve R5F1/R5F2/R5G semantics and frozen identities; harden migration `20260807_0006`; no new revision, CLI mapping changes, numerical formula changes, or MIN-007H work.

### MIN-007R5F3 checkpoints

- [x] Add DRAFT/COMPLETE lifecycle boundaries and database triggers for dataset, core graph, and final output.
- [x] Add strict model evaluation provenance envelope and durable binding fields.
- [x] Run all 24 literal acceptance commands, record evidence, remove PostgreSQL, commit once, and verify a clean worktree.

## MIN-007R5G - CLI public assurance remediation

- Ticket/stage: `MIN-007R5G`, A7; required parent `2986433e32d55aa3153003b3cc98a098c3a9c071`.
- Scope: close AUDIT-007-3 findings 9–12 only: strict CLI cutoff/seed semantics, data-driven synthetic mapping, superseding public probability schema, portable repository goldens, substantive PostgreSQL G persistence, and all-scenario CLI assurance.
- Constraints: preserve MIN-007R5F1/F2 architecture and frozen model/registry identities; no migration, Stage-7H work, live provider/network/credential access, or numerical formula changes.

### MIN-007R5G checkpoints

- [x] Reconcile existing implementation against the corrected R5G contracts and add repository-contained authority assets and portability guards.
- [x] Implement strict cutoff/seed/mapping/public-schema semantics and substantive PostgreSQL/CLI assurance regressions.
- [x] Run all 23 literal acceptance commands, record evidence, remove PostgreSQL, commit once, and verify a clean worktree.

## MIN-007R5F2 - relational and evaluation integrity remediation

- Ticket/stage: `MIN-007R5F2`, A7; required parent `6fc063424ed8e5c4a688432ccf54770f0c8137eb`.
- Scope: close only AUDIT-007-3 findings 6–8: canonical PMF arrays and exact HALF_EVEN projection checks, scenario/final cross-graph coherence, and strict model-bound evaluation persistence.
- Constraints: modify only unmerged migration `20260807_0006`; preserve R5F1 atomicity and all frozen F/G identities; do not fix CLI/public-schema/P2 findings or start MIN-007H.

### MIN-007R5F2 checkpoints

- [x] Add focused public identity, DB relational/numeric, and evaluation integrity regressions.
- [x] Run all 23 literal acceptance commands, record evidence, remove PostgreSQL, and create the single bounded ticket commit.

## MIN-007R5F1 - registry identity and publication atomicity remediation

- Ticket/stage: `MIN-007R5F1`, A7; required parent `7ed2379f551690f04b85dc53a45237f649990894`.
- Scope: close only AUDIT-007-3 findings 1-5: typed semantic hash allowlists, atomic/complete dataset lineage, model artifact conflict truthfulness, prediction graph atomicity/completeness, and recomputed output identity.
- Constraints: preserve frozen B-G identities and Alembic head `20260807_0006`; no fixes for findings 6-12, no new migration revision, no MIN-007H.

### MIN-007R5F1 checkpoints

- [x] Implement typed registry normalization, DB-gated completeness, conflict checks, publication state/atomicity, and output-hash recomputation with focused regressions.
- [x] Run all 20 literal acceptance commands, record evidence, tear down PostgreSQL, and create the single bounded ticket commit.

## MIN-007G - final minutes projection, synthetic evaluation and CLI

- Ticket/stage: `MIN-007G`, A7; required parent `9ca984b785b681531b7c0648cfbbb45c436dc075`.
- Scope: compose the accepted C/D/E outputs into strict public player/team projections, freeze synthetic evaluation, persist final projections/evaluations through the MIN-007F reserved tables, and expose the TEST/REPLAY availability CLI.
- Constraints: no migration, no Stage-8 logic, no live provider/network/credential access, preserve all frozen B/C/D/E/F identities and Alembic head `20260807_0006`.

### MIN-007G checkpoints

- [x] Read and validate the G pack; confirm branch, parent, clean worktree, and Alembic head.
- [x] Implement pure projection, pipeline, evaluation, strict public models, fixture loader, and CLI with focused tests.
- [x] Integrate final projection/evaluation persistence without changing the F schema.
- [x] Run all 24 literal acceptance commands, collect evidence, remove PostgreSQL, and create exactly one bounded ticket commit.

## MIN-007F - PostgreSQL registry, persistence and historical as-of

- Ticket/stage: `MIN-007F`, A7; required parent `0e3b21a702fece94cb0ee6d61867e6fb17574d0a`.
- Scope: immutable dataset/example lineage, model/evaluation registry, prediction bundle persistence, exact numeric database constraints, concurrency-safe idempotency, and historical as-of lookup.
- Constraints: preserve frozen B/C/D/E identities; no final minute mixture, evaluation calculation, CLI, provider, Stage-8, or Stage-9 code.

### MIN-007F checkpoints

- [x] Implemented registry hashes, PostgreSQL migration `20260807_0006`, persistence repositories, and focused tests.
- [x] Ran all 22 literal acceptance commands, recorded evidence, tore down PostgreSQL, and prepared the single bounded ticket commit.

## MIN-007R4 - exact Decimal boundary hardening

- Ticket/stage: `MIN-007R4`, A7; required parent `1ea36d831e18157a669b257a3761f8a9c9a5cdf7`.
- Scope: context-independent exact stored minute-PMF simplex/correction, exact candidate START+BENCH inequality, adversarial regressions, and ticket evidence.
- Constraints: preserve frozen precision-60 calculations and B/C/D/E identities; no sampler, mixture, persistence, CLI, provider, network, or MIN-007F work.

### MIN-007R4 checkpoints

- [x] Implemented the shared exact finite-Decimal invariant utility and focused boundary probes.
- [x] Ran all 15 literal acceptance commands, recorded evidence, and prepared the single bounded ticket commit.

## MIN-007R3E - harden coherent lineup invariants

- Ticket/stage: `MIN-007R3E`, A7; required parent `9848c3ff3d68d75e31ffa55085ff033177aec312`.
- Scope: one-to-one candidate identity, context-independent weight constraints, strict seed suffixes, and truthful projected-result validation.
- Constraints: preserve frozen B/C/D/E identities and race algorithm; do not begin MIN-007F.

### MIN-007R3E checkpoints

- [x] Implemented the four AUDIT-007-2 lineup remediations and focused adversarial probes.
- [x] Run all acceptance commands, record evidence, and create the single bounded ticket commit.

## MIN-007R3D - harden conditional minute invariants

- Ticket/stage: `MIN-007R3D`, A7; required parent `64f6b168db496c6c3aabe39dda82ad7843266a2a`.
- Scope: exact stored Decimal conditional-PMF simplex, UUID-shaped example duplicate identity, and validated minute-result copy boundaries.
- Constraints: preserve frozen B/C/D/E identities; do not modify `lineup.py` or begin MIN-007F.

### MIN-007R3D checkpoints

- [x] Implemented the three assigned AUDIT-007-2 D remediations and focused adversarial tests.
- [x] Run all acceptance commands, record evidence, and create the single bounded ticket commit.

## MIN-007E - coherent lineup sampler

- Ticket/stage: `MIN-007E`, A7.
- Required branch/parent: `stage/A7/MIN-007-basic-minutes-model` from `60c583aa5dafff90aeaf2647d2b6cf9eeef950e9`.
- Scope: deterministic Decimal exponential-race sampling of coherent 11-player lineups and configured benches.
- Constraints: preserve accepted A/B/C/D identities; no minute-PMF coupling, overall minute projection, persistence, CLI, evaluation, network, provider, or credential work.

### MIN-007E checkpoints

- [x] 2026-08-10 - Implemented the exact four-phase Decimal sampler, typed projected/blocked results, semantic scenario hashes, and focused tests.
- [x] 2026-08-10 - Ran all 15 literal acceptance commands with zero final failures, recorded evidence, and prepared the exact ticket commit pending final clean-tree verification.

## MIN-007D - conditional minutes PMFs

- Ticket/stage: `MIN-007D`, A7.
- Required branch/parent: `stage/A7/MIN-007-basic-minutes-model` from `6d31e3e46a9f3609efab9a2a9ca28f269b5ef6bb`.
- Scope: fit typed Decimal START/BENCH minute priors and predict cutoff-safe conditional 91-point minute PMFs.
- Constraints: preserve accepted A/B/C/R1/R2 and NRM identities; no coherent sampler, public role marginals, overall player PMF, persistence, CLI, evaluation, network, provider, or credential work.

### MIN-007D checkpoints

- [x] 2026-08-10 - Implemented Decimal position/role minute priors, cutoff-safe conditional PMFs, reduced synthetic weighting support, and focused unit/property/golden tests; frozen artifact and independent canaries pass.
- [x] 2026-08-10 - Ran all 15 literal acceptance commands with zero final failures, recorded evidence, and prepared the exact ticket commit pending final clean-tree and review-pack validation.

## MIN-007R2 - explicit new-signing identity override

- Ticket/stage: `MIN-007R2`, A7.
- Required branch/parent: `stage/A7/MIN-007-basic-minutes-model` from `11acd4a0f7eee89a7c59ca5209dfa89999627145`.
- Scope: require explicit validated boolean `new_signing: true` for distinct canonical player-ID overrides and add direct identity/evidence-ownership regressions.
- Constraints: preserve all accepted A/B/C/R1 and NRM identities; no 007D work, dependency, network, provider, credential, database, migration or CLI changes.

### MIN-007R2 checkpoints

- [x] 2026-08-10 - Added the distinct-identity guard and direct missing/false/true/collision/cold-start/same-UUID regressions.
- [x] 2026-08-10 - Ran all 13 literal acceptance commands with zero final failures, recorded evidence, and prepared the exact ticket commit pending final clean-tree verification.

## MIN-007R1 - AUDIT-007-1 remediation

- Ticket/stage: `MIN-007R1`, A7.
- Required branch/parent: `stage/A7/MIN-007-basic-minutes-model` from `2be9852da08913a07678bd6235edbe56d6a4664d`.
- Scope: strict UTC timestamp boundaries, shared history identity validation, full-precision Decimal role utilities, canonical-ID override collision rejection and concrete frozen-schema negative tests.
- Constraints: preserve all accepted A/B/C hashes, canaries, coefficients and NRM schemas; no 007D work, dependency, network, provider, credential, database, migration or CLI changes.

### MIN-007R1 checkpoints

- [x] 2026-08-09 - validated the remediation pack, reproduced all four P1 probes, implemented the five narrow remediations and added direct regression coverage.
- [x] 2026-08-09 - ran all 16 literal acceptance commands with zero failures, recorded evidence, and prepared the single frozen-parent remediation commit pending final clean-tree verification.

## MIN-007C - regularised role baseline

- Ticket/stage: `MIN-007C`, A7.
- Required branch/parent: `stage/A7/MIN-007-basic-minutes-model` from `d54eae162386901f9710d7212b5dfb89174cfa31`.
- Scope: fit frozen position START/BENCH/OUT priors and produce cutoff-safe internal role sampling utilities with explicit confidence metadata, manager/preseason weighting and trusted hard-ineligibility handling.
- Constraints: no PMFs, coherent lineup sampler, public coherent marginals, persistence/migration, CLI, evaluation, dependency, network/credential, or redesign of MIN-007A/MIN-007B.

### MIN-007C checkpoints

- [x] 2026-08-09 - validated Pack 007C (`21` manifest entries; frozen artifact and nine-canary oracle PASS), confirmed the exact MIN-007B parent and clean preflight, and read the frozen role contract/oracles.
- [x] 2026-08-09 - implemented the pure Decimal role baseline, reproduced the frozen artifact and nine canaries, passed the 13-command ledger, and prepared the exact bounded commit with clean-tree verification pending after commit.

## MIN-007B - cutoff-safe minutes training dataset builder

- Ticket/stage: `MIN-007B`, A7.
- Required branch/parent: `stage/A7/MIN-007-basic-minutes-model` from `84697a464af17a909e28a6870d764617098fc30a`.
- Scope: create the pure, deterministic, synthetic-history-to-TRAIN-dataset slice with explicit role/minutes labels, cutoff-safe eligibility, canonical ordering, duplicate rejection and semantic hashing.
- Constraints: no role model, PMFs, lineup sampler, persistence/migration, CLI, evaluation, dependency, network/credential, or MIN-007A market changes.

### MIN-007B checkpoints

- [x] 2026-08-09 - validated Pack 007B (`17` hashed files; frozen dataset oracle PASS), confirmed the exact MIN-007A parent and clean worktree, and read the D1-D9 contract and stop rules.
- [x] 2026-08-09 - implemented and verified the pure cutoff-safe builder against the frozen 368-row oracle, passed the literal acceptance ledger, and prepared the exact bounded commit with clean-tree verification pending after commit.

## MIN-007A - NRM public-contract and confidence hardening

- Ticket/stage: `MIN-007A`, A7.
- Required branch/parent: `stage/A7/MIN-007-basic-minutes-model` from `253baf3f19661a5704bb1fad2f7ac60e1db288eb`.
- Scope: install the three supplied superseding NRM public schemas, preserve the probability dependency, and separate ordinary degradation evidence from blocking confidence warnings without changing NRM math, policy, freshness, persistence, or database objects.
- Constraints: offline synthetic fixtures only; no provider/network/credential, dependency, migration, minutes model, broad refactor, push, merge, rebase, reset, tag, or amend.

### MIN-007A checkpoints

- [x] 2026-08-09 - validated Pack 007A (`23` hashed files), confirmed the exact branch/parent and clean worktree, read the frozen H1/H2 contracts, and passed the pre-edit focused NRM contract/unit/golden suite (`73 passed`).
- [ ] Final - install exact schemas, add negative and canary regressions, pass all literal commands, commit with the exact ticket message, and leave the worktree clean.

## NRM-006 - odds normalisation and consensus baseline

- Ticket/stage: `NRM-006`, A6.
- Required branch/baseline: `stage/A6/NRM-006-odds-normalisation` from `e36ea84cda9e80191a9160d037f8e7035477b9b1`.
- Outcome: close every frozen ODD-005 temporal/provenance finding, then transform complete operator-specific full-time 1X2 observations into exact raw implied, proportional, power, equal-operator consensus, uncertainty, freshness, confidence, and immutable as-of output.
- Constraints: offline synthetic/fake/scripted inputs only; no real credential, additional provider, raw odds redistribution, Shin production, exchange/player-prop/other market family, learned calibration, forecast, optimiser, scheduler, API/UI, new dependency, SQLite, push, merge, rebase, reset, tag, or amend.

### NRM-006 checkpoints

- [x] 2026-08-06 - validated corrected Pack 1.1 (79 manifest entries, 80 detached checksums, zero errors), exact branch/base and sole permitted Pack 1.0 blocker residue, complete corrected quota fixture, Docker/Compose/PostgreSQL 18.4, Alembic head `20260725_0004`, and the inherited suite at 882 passed with zero skips.
- [x] NRM-006.0 - preserved the Pack 1.0 blocker byte-for-byte and recorded Pack 1.1 quota and post-commit-attestation authority resolution.
- [x] NRM-006.1 - implemented post-commit publication attestation and cutoff-safe historical mapping across odds promotion and strict reads.
- [x] NRM-006.2 - closed 429 retry, synthetic provenance, duplicate-evidence, reobservation-lineage, and mapping-validity findings.
- [x] NRM-006.3 - implemented exact Decimal proportional/power normalisation, operator grouping, consensus, uncertainty, freshness, confidence, and frozen goldens.
- [x] NRM-006.4 - added immutable PostgreSQL persistence, reversible `20260803_0005` migration, as-of/cache/concurrency guarantees, CLI/API, wheel, and assurance tooling.
- [x] 2026-08-06 - passed pre-commit Ruff, strict mypy, PostgreSQL migration, golden, temporal, installed-wheel, security, critical-coverage, and full-suite gates; the final full regression recorded 1,056 passed with zero skips before the fail-closed Windows entry-point hardening, whose focused unit and installed-wheel checks also passed.
- [x] 2026-08-06 - closed the subsequent independent P1 audit findings: post-commit clock ownership, single-budget retry/quota behavior, canonical duplicate identity, historical mapping/rights/quality revalidation, operator/fixture grouping, policy-driven confidence, code/dependency identity, relational lineage, and correction concurrency. The post-remediation full suite, migration/concurrency matrix, static gates, and focused security/temporal checks passed with zero skips; a final independent read-only audit found no remaining P0/P1 issue.
- [x] 2026-08-06 - the first literal acceptance run passed commands 1-25, then command 26 exposed that its fresh wheel database seeded the FPL schedule after the requested market cutoff. Preserved the strict temporal rejection, changed only the verifier to import the approved synthetic schedule before the cutoff, and proved the isolated installed wheel end to end before restarting the complete ledger.
- [ ] Final - resolve independent P0/P1 review, commit the green ticket, run all 32 literal acceptance commands, and validate the capped root-only review ZIP.

### NRM-006 decision log

- Pack 1.1 preserves the inherited all-or-nothing quota-header rule and corrects the frozen retry fixture; partial evidence stays invalid.
- Strict eligibility requires an immutable post-commit attestation. Canonical activation and USABLE lifecycle commit atomically first; the injected clock is sampled only after acknowledgement, and failed attestation cannot backdate recovery.
- Strict replay uses one explicit mapping cutoff for valid/system-time mappings, aliases, and attested fixture schedule observations. Synthetic evidence is TEST_ONLY and cannot assert official-source verification.
- POWER is primary and PROPORTIONAL is retained baseline/fallback under local Decimal precision 60, HALF_EVEN, exactly 256 bisections, and exact 12-place public vector residual handling.
- Normalise complete operator books separately, then use equal canonical-operator consensus. No cross-operator book, stale fill, learned weight, or future-stage market/model capability is permitted.
- Exact dependency signatures and immutable source-observation IDs govern cache reuse; equal prices from a later retrieval retain distinct run/evidence lineage.

## ODD-005 - FPL remediation and odds-provider foundation

- Ticket/stage: `ODD-005`, A5.
- Required branch/baseline: `stage/A5/ODD-005-odds-provider-foundation` from `7034e38f32cd579c90d35c5fe3f10921c3656be0`.
- Outcome: close the frozen FPL-004 review findings, then ingest manifest-approved synthetic The-Odds-API-shaped EPL 1X2 books into immutable rights/quota/source evidence, explicit canonical mappings, exact Decimal observations, and cutoff-safe as-of queries.
- Constraints: no live provider request or real API key; one provider/competition/region/market only; no name-only merge, probabilities, normalisation, consensus, forecasts, scheduler, API/UI, betting action, new dependency, SQLite, push, merge, rebase, reset, tag, or amend.

### ODD-005 checkpoints

- [x] 2026-07-25 - verified the exact branch/base/clean-tree gates, all 63 detached pack hashes and 62 manifest entries, Docker Desktop/Compose/PostgreSQL 18.4, Alembic head/current `20260724_0002`, and the unchanged inherited suite at 589 passed with zero skips.
- [x] 2026-08-02 - resumed the preserved Pack 1.0 worktree under hash-validated corrected Pack 1.1, resolved the frozen decimal lexical-policy blocker, confirmed the exact branch/base, and passed 90 focused offline plus 19 PostgreSQL migration/ingestion tests before further implementation edits.
- [x] ODD-005.1 - installed the frozen ticket/contracts/schemas/fixtures and completed all six mandatory FPL-004 remediations with direct negative controls.
- [x] ODD-005.2 - implemented the strict provider/client/quota boundary, rights profiles, payload semantics, explicit mappings, and exact domain models.
- [x] ODD-005.3 - added the reversible PostgreSQL market schema, bundle publication guards, immutable persistence, idempotency/concurrency, and deterministic as-of query.
- [x] ODD-005.4 - exposed the approved CLI/public contracts and installed-wheel replay/query/refusal slice.
- [x] ODD-005.5 - passed focused, full, migration, coverage, security, and independent read-only review gates with no unresolved P0/P1 finding.
- [ ] Final - commit the accepted ticket, run all 28 literal commands from a clean commit, record measured evidence, and validate the root-only maximum-20-file review ZIP.

### ODD-005 decision log

- The Odds API v4 is the sole Stage A5 provider; `soccer_epl`, `uk`, and `h2h` are frozen, while all implementation and acceptance transport is fake/offline.
- Provider event and bookmaker keys require explicit provider-scoped mappings; raw labels validate an already resolved identity and never create one.
- Stage A5 stores offered Decimal odds only. Implied probabilities, margin removal, consensus, forecasting, and betting guidance remain excluded.
- `usable_at <= as_of` is the sole eligibility boundary; later retrievals and corrections append history and cannot alter an earlier query result.
- The repository stores Alembic revisions under the ticket-allowed `src/dmf_pulse/database/**` tree; add one ordered revision there and never rewrite a prior revision.
- The mandatory inherited FPL remediations extend existing shared ingestion primitives for rights-decision idempotency, source envelopes, fixture authority, and exit taxonomy. Those bounded shared edits, `PLANS.md` required by repository governance, and the exact-path security-fixture allowlist are contract-enabling changes; they introduce no new provider or future-stage surface.
- Final pre-commit verification: 882 tests passed with zero skips/warnings; combined coverage 93.44%, overall branch coverage 90.18%, and all critical ODD/FPL remediation branch gates 100%; the PostgreSQL 18.4 migration/preservation matrix, installed wheel, secret scan, repository validator, lint, formatting, typing, frozen-input validation, CLI replay/query/refusal, and three independent read-only audits passed.

## FPL-004 - rights-gated official FPL ingestion foundation

- Ticket/stage: `FPL-004`, A4.
- Required branch/baseline: `stage/A4/FPL-004-official-ingestion` from `9b3160a2574d2868b5f26e3a2d429924567510b0`.
- Outcome: remediate DAT-003 lifecycle and relational P1 findings, then ingest approved synthetic FPL-shaped bootstrap/fixtures into immutable retrieval evidence, season-scoped canonical mappings, typed observations, quality records, and a deterministic cutoff-safe source bundle.
- Constraints: no live FPL/provider request, real FPL payload, authenticated endpoint, automated polling, persistent official-profile raw/derived storage, name-only merge, new dependency without approval, SQLite, models, optimiser, API/UI, push, merge, rebase, reset, tag, or amend.

### FPL-004 checkpoints

- [x] 2026-07-24T20:43:21+01:00 - verified exact branch/baseline/clean-tree preconditions, Pack 004 hashes and synthetic fixture oracles, Docker/PostgreSQL 18.4, accepted DAT-003 head/schema, and the 279-test inherited baseline.
- [x] 2026-07-25T09:27:45+01:00 - FPL-004.0: closed every mandatory DAT-003 remediation with reversible PostgreSQL constraints and direct adversarial regression tests.
- [x] 2026-07-25T09:27:45+01:00 - FPL-004.1: implemented immutable versioned Rights Profiles, fail-closed decisions, isolated service-owned volatile copies for ordinary official manual-import paths, crash/concurrency-safe cleanup, and rights-before-transport behavior.
- [x] 2026-07-25T09:27:45+01:00 - FPL-004.2: implemented retrieval envelopes, append-only lifecycle, authority-bound suffix-only resume, pair locking, and derived usability.
- [x] 2026-07-25T09:27:45+01:00 - FPL-004.3: implemented strict bounded payload parsing, schema drift/missingness, season-scoped canonical mappings, immutable observations, quality records, atomic promotion, and cutoff-safe bundles.
- [x] 2026-07-25T09:27:45+01:00 - FPL-004.4: exposed the public CLI and frozen HTTP boundary; 524 tests, strict typing/lint, PostgreSQL migration/concurrency proofs, and 92.30% combined branch coverage pass locally.
- [x] 2026-07-25T12:18:12+01:00 - FPL-004.5 interruption recovery review: resolved installed exit-code propagation, immutable/strict rights parsing, actual system-time resume and bitemporal semantics, atomic honest promotion, A-B-A observation history, exact retrieval bundle manifests, ingestion run/attempt linkage, strict RFC3339 and transport failures, provider/effective configuration lineage, durable pre-parse raw read-back, and false-COMPLETE archive write-ahead evidence. Focused offline suites (178), unit suite (416), and lifecycle/bundle/security PostgreSQL suite (28) pass.
- [x] 2026-07-25T13:25:24+01:00 - FPL-004.6 final stabilization: made temporal canonical supersession source-time ordered, added transactional same-time semantic-observation claims, proved mixed-payload contradiction rollback and old-replay non-supersession, hardened error-body transport translation and installed-wheel fixture replay, and closed detached-log/teardown false-COMPLETE paths. Three independent read-only audits found no unresolved P0/P1. The 589-test preacceptance run exposed one evidence-script import defect; its regression now passes. Actual coverage evidence passes the authority-tiered gates at 91.42% combined, 98.33% critical deterministic, 94.44% rights, 84.62% provider, and 100% cutoff predicates.
- [x] 2026-07-25T13:40:01+01:00 - FPL-004.7 first literal-run finding: commands 1-23 and guaranteed teardown passed, but command 24 preparation failed closed because the privacy scanner found its own lowercase personal-data sentinel in the complete patch after title-case-only redaction. Redaction now removes the full owner name, username, surname, and Windows user paths case-insensitively, including self-referential scanner literals; the focused 17-test review-pack suite, Ruff, and strict mypy pass. A clean full rerun remains required.
- [x] 2026-07-25T13:44:32+01:00 - FPL-004.8 second literal-run finding: commands 1-10 passed, then the pre-PostgreSQL security partition exposed six database-dependent tests inheriting the module-wide `security` marker. The three offline rights/path tests now carry `security` explicitly, while the six already-`postgres` tests remain exercised by literal command 18 and the full suite after command 12. Exact command 11 passes with PostgreSQL down: 6 passed, 6 deselected, zero skips.
- [ ] Final - run all 25 literal acceptance commands, complete ordered self-review, record the final clean commit, and validate the exact 20-file review ZIP.

### FPL-004 decision log

- The supplied rights register is controlling engineering policy, not legal advice. Unknown rights deny; technical reachability never grants permission.
- Only `synthetic_test_v1` authorizes persistent FPL-004 promotion and bundle creation. `fpl_official_private_manual_v1` is bounded transient validation only and blocks transport before any live snapshot request.
- Every retrieval has one immutable envelope and append-only lifecycle. Current state and first `usable_at` are derived; legacy DAT-003 lifecycle columns are compatibility data only for new ingestion.
- Canonical IDs never derive from FPL IDs or names. Provider mappings are provider/resource/type/season scoped, and conflicts quarantine instead of guessing.
- Source-bundle membership is selected from derived `USABLE` state at or before the declared cutoff; provider-generated time is never a substitute.
- No real FPL body may enter Git, PostgreSQL, logs, evidence, or the review ZIP during this milestone.
- Provider and rights JSON are strict packaged runtime authorities. Resume and bundles bind their separate hashes plus one effective configuration hash.
- Equivalent payload pairs share a semantic bundle hash but retain separate immutable exact-manifest bundles and source snapshot membership.
- Commands 24-25 remain `PENDING` in a `BLOCKED` preliminary archive; only measured final records after guaranteed teardown may produce a detached-validator-accepted `COMPLETE` archive.

## DAT-003 - canonical temporal PostgreSQL foundation

- Ticket/stage: `DAT-003`, A3.
- Required branch/baseline: `stage/A3/DAT-003-canonical-foundation` from `f9b51e965aad1bc94796c17c897f0d99b4c16e1b`.
- Outcome: close all blocking RUL-002 findings and deliver a PostgreSQL 18.4 vertical slice for UUIDv7 canonical identity, bitemporal corrections/as-of reads, immutable provenance, rules activation registry, reversible migrations, deterministic CLI, and governed evidence.
- Constraints: disposable local PostgreSQL only; no provider/network access, SQLite, future ontology, models, optimiser, API/UI, account actions, push, merge, rebase, reset, tag, or amend.

### DAT-003 checkpoints

- [x] 2026-07-23T09:00:00Z - verified Pack 003 hashes and exact baseline/branch, captured context evidence, and passed the existing 200-test foundation/rules baseline.
- [x] 2026-07-23T12:00:00Z - closed RUL-002 P1 findings R1-R8 with direct regression tests while preserving corrected v1.1 goldens.
- [x] 2026-07-23T15:00:00Z - added the pinned PostgreSQL/SQLAlchemy/Alembic/Psycopg toolchain, exact 20-table migration, UUIDv7/temporal/provenance constraints, functions, triggers, views, schema fingerprint, and downgrade/re-upgrade checks.
- [x] 2026-07-23T18:00:00Z - implemented explicit repositories and deterministic doctor/schema/demo/as-of CLI with PostgreSQL boundary, concurrent overlap, immutability, rules-registry, clean-wheel, and negative error tests.
- [x] 2026-07-23T20:00:00Z - strengthened independent branch/mutation oracles to meet the 90% overall, 98% rules, and 92% combined data-model/database gates in focused measurement.
- [ ] Final - run the literal 23-command acceptance ledger with guaranteed teardown, generate actual-commit evidence, and validate the exact 20-file review ZIP.

### DAT-003 decision log

- PostgreSQL 18.4 server `uuidv7()` is authoritative for persisted identifiers; application code never manufactures persisted UUIDs.
- Valid time and system-known time are independent closed-open ranges. Corrections close only the superseded system interval and preserve historical rows.
- Source-less initial fixture assignments/revisions are permitted where the public contract makes provenance optional; every correction requires distinct usable provenance.
- `validation_status = USABLE` is equivalent to non-null `usable_at`, enforced in PostgreSQL and typed models.
- The test credential is the literal fake `changeme`; committed settings retain only the `env:DMF_TEST_DATABASE_URL` reference.
- The review command uses stable write-ahead records for commands 22-23, then refreshes the same deterministic archive after finally-guaranteed teardown without invoking command 22 twice.

## RUL-002 — governance remediation and rules foundation

- Ticket/stage: `RUL-002`, A2.
- Required branch/baseline: `stage/A2/RUL-002-rules-foundation` from `12049a7de23a4a8fcca3d219dbcab1bf5e1027ea`.
- Outcome: generic governed evidence, a strict split-YAML rules compiler and lifecycle, pure fixture/Gameweek scoring, deterministic CLI contracts, and a validated review ZIP capped at 20 root files.
- Authority: official target-season rules/provider terms; newest ACTIVE/ACCEPTED DMFP-20 decision; most-specific accepted module; DMFP-00; earlier research; implementation convenience. Ticket contracts are subordinate execution constraints.
- Constraints: offline; no new dependencies; no database/provider/model/optimiser/UI code; no activation or inferred completion of the partial 2026/27 ruleset; no push or merge.

### RUL-002 checkpoints

- [x] 2026-07-22T12:00:00Z — verified the v1.1 correction notice, all pack and fixture hashes, corrected independent oracles, exact baseline/branch/clean-tree preconditions, and the 104-test FND baseline.
- [x] 2026-07-22T14:28:55Z — RUL-002.0: generated the complete 94-entry DMFP-20 index, hash-pinned stage authority requirements, generic ticket/evidence/review contracts, and exact runtime lock graph; authority and assurance targeted tests pass.
- [x] 2026-07-22T14:28:55Z — RUL-002.1: implemented strict safe-subset YAML, exact typed authoring schemas and cross-file coherence, deterministic compilation/hash/diff, in-memory integrity revalidation, and atomic immutable lifecycle gates.
- [x] 2026-07-22T14:28:55Z — RUL-002.2: implemented pure configured scoring/BPS/competition-ranking/Gameweek aggregation; corrected v1.1 goldens plus boundary, property, lifecycle, schema, and false-success mutation probes pass with 98.84% rules branch coverage in the focused run.
- [x] 2026-07-22T15:14:18Z — RUL-002.3: exposed all rules CLI commands, updated package/docs/least-privilege CI, and passed the final precommit quality gate with 200 tests, zero skips, 90.81% overall branch coverage, 98.88% rules branch coverage, frozen-lock validation, clean-wheel verification, repository validation, and secret scanning. The exact 19-command final ledger, actual-commit evidence, and 20-file ZIP are deliberately generated from the clean committed tree into ignored evidence/review paths.
- [x] 2026-07-22T15:19:54Z — RUL-002.4: the first post-commit ledger run exposed a strict-prefix defect for otherwise successful rules commands; changed the generic success summary to the required `PASS:` form and added a focused false-failure regression test before rerunning acceptance from a new commit.

### RUL-002 decision log

- The v1.1 fixture family is immutable input. No v1.0 digest, expected output, or manifest is admissible.
- The checked 2026/27 deltas remain `CAPTURED_UNVERIFIED`; all unannounced rule families are typed blockers, so scoring/activation cannot guess.
- The reference/synthetic scorer consumes only compiled configuration and explicit aggregate scenario facts. Zero-minute Gameweek placeholders are excluded from BPS/bonus ranking.
- `payload_sha256` is the stable detached primary-payload digest. `archive_sha256` is reported only after ZIP creation and cannot be embedded as a self-hash.
- Command 19 is invoked exactly once against a write-ahead ledger; after the invocation, its measured duration replaces the provisional entry and the same assembler refreshes the final archive without rerunning the CLI command. Final archive digest/CRC evidence remains external to avoid self-reference.
- Two narrow ticket-required changes fall outside the enumerated `allowed_areas`: `src/dmf_pulse/__init__.py` is the existing canonical version source that must become `0.2.0`, and `.gitignore` must exclude regenerable RUL evidence so COMPLETE evidence can name the actual commit while the final tree remains clean. No other out-of-list path is changed.

---

# FND-001 historical execution plan

## Ticket and outcome

- Ticket: `FND-001`, Stage A0/A1 foundation milestone
- Branch: `stage/A1/FND-001-foundation`
- Owner: Sebastian Greenhalgh
- Implementation lead: Codex
- Independent reviewers: fresh read-only scope/security/test-gap review before acceptance
- Observable outcome: a governed, reproducible Python 3.13 workspace with an installed `dmf` CLI, strict configuration, diagnostics, first-party assurance tooling, CI, machine-valid evidence, and a review ZIP capped at 20 root files.

## Authority and decisions

- Precedence: accepted DMFP-20 decisions; FND-001 ticket/acceptance details; most-specific DMFP module; DMFP-00; implementation playbook/repository guidance.
- Controlling decisions: `ADR-PROD-004`, `ADR-GOV-001`, `ADR-GOV-002`, `ADR-GOV-004`, `ADR-RES-001`, `ADR-DATA-002`, `ADR-SRC-001`, `ADR-IMPL-001`, `ADR-IMPL-002` (provisional), and `ADR-IMPL-003`.
- Primary locators: DMFP-19 §7 Stage 1; DMFP-17 §§0.5, 0.8–0.9, and 4; DMFP-20 §0 and the decision blocks above; FND-001 acceptance and review-pack contracts.

## Baseline

- Captured before all other repository changes at `evidence/tickets/FND-001/baseline_manifest.json`.
- Existing Git HEAD: `44e63a9f2acf6627912f9a0b6d5173553db0895f` (empty initial commit).
- Existing non-`.git` files: zero.
- Remote owner parsed unambiguously as `sebgreenhalgh`; no remote mutation is authorised.
- Pack integrity: all 42 files listed by `PACK_MANIFEST.json` matched expected bytes and SHA-256.

## Ordered checkpoints

1. Install all 21 approved DMFP documents verbatim, install the implementation playbook, generate authority/document/decision manifests, and validate hashes/references/DMFP-04 edition.
2. Add concise governance, ticket records, schemas, security/contribution guidance, cross-platform operations documentation, and CODEOWNERS derived only from the remote.
3. Add the Python 3.13 `src/` package, Hatchling build, canonical `0.1.0` version, approved dependencies, exact uv lock, and clean-wheel verifier.
4. Implement and test strict Pydantic v2 configuration, deterministic overlays/redaction, Typer CLI, injected clock/process boundaries, and nonblocking hardware diagnostics.
5. Implement canonical JSON/hashing, typed evidence models/validation, manifest/repository validation, secret scanning, deterministic baseline diffing, and capped review-pack creation.
6. Complete unit/property/golden/integration coverage with offline/home isolation and achieve at least 90% branch coverage for `dmf_pulse`.
7. Add least-privilege Ubuntu CI plus scheduled/manual Windows smoke; mirror local uv/Python commands.
8. Run every mandatory command literally, record command/exit/duration evidence, conduct ordered read-only self-reviews, fix material findings, and generate/validate the final ZIP.

## Test map

- Package/CLI: installed version, installed module path, `py.typed`, JSON and human rendering, stable exit/error codes.
- Configuration: strict fields, required/malformed values, overlay precedence, path normalization, timezone/log/device validation, raw-secret rejection, deterministic/redacted output, no directory creation.
- Doctor/system: injected time/processes, safe write probe cleanup, timeout/truncation, GPU absence healthy, no identity/secret fields.
- Assurance: canonical hash stability, hash mismatch/missing/duplicate/stale reference/paid-DMFP-04 failures, schema failures, fake-secret shapes and allowlisting, review-pack 21-file refusal and detached-manifest hashes.
- Isolation: package imports cannot invoke network/subprocess/write/environment mutation; tests use no network or user home.

## Acceptance commands

The 13 literal commands in `03_ACCEPTANCE_CONTRACT.md` are mandatory, followed by installed-wheel `dmf --version` and `dmf doctor --json` in a fresh environment outside the repository. Every invocation will be recorded separately with command, exit code, duration, and concise result.

## Risks and safe fallback

- Local `python`/`uv` execution may require the approved absolute uv path because managed sandbox policy denied PATH-resolved executables; use the sanctioned uv installation and request only the narrow dependency/network permission if resolution fails.
- Zoneinfo data on Windows can vary; validation must use the Python 3.13 runtime’s available `zoneinfo` data and provide actionable failure output without adding an unapproved runtime dependency.
- Review ZIP output is requested both in-repository and beside the source pack; generate and validate in-repository first, then copy the final ZIP to the external requested destination without changing Git history.

## Progress

- [x] 2026-07-22T09:11:21Z — inspected Git status, remote, branches, HEAD, and empty tree.
- [x] 2026-07-22T09:11:21Z — captured deterministic empty-repository baseline as the first artifact.
- [x] 2026-07-22T09:11:21Z — read the controlling pack in the mandated order and verified all 42 pack hashes/byte counts.
- [x] 2026-07-22T09:20:00Z — Checkpoint 0 complete: installed 21 exact DMFP files plus playbook, generated three governed manifests, and passed the first-party validator with zero errors.
- [x] 2026-07-22T09:20:39Z — Checkpoint 1 complete: added governance, proprietary licensing, ticket records, Codex contracts, owner-derived CODEOWNERS, and cross-platform operational documentation; manifest validation remained green.
- [x] 2026-07-22T09:48:18Z — Checkpoint 2 complete: uv resolved 29 packages for Python 3.13.9, frozen sync passed, and the wheel verified `py.typed`, installed module provenance, version, doctor, and cleanup outside the source tree.
- [x] 2026-07-22T09:48:18Z — Checkpoint 3 complete: strict configuration, deterministic overlays/redaction, path/timezone/reference semantics, and no-create loading passed targeted unit/property tests.
- [x] 2026-07-22T10:50:31Z — Checkpoint 4 complete: deterministic CLI/doctor contracts, privacy-minimized bounded probes, missing-config blocking, safe CPU fallback, and installed default timezone validation passed.
- [x] 2026-07-22T10:50:31Z — Checkpoint 5 complete: canonical evidence/hashing, fail-closed secret scan, manifest integrity, detached primary-payload digest, atomic capped review ZIP, and negative tamper tests passed.
- [x] 2026-07-22T10:50:31Z — Checkpoint 6 complete: 103 offline tests passed with 288/318 branches covered (90.57%) and strengthened import/network/write/logging false-success traps.
- [x] 2026-07-22T10:50:31Z — Checkpoint 7 complete: least-privilege Ubuntu CI, scheduled/manual Windows smoke, exact frozen commands, cross-platform documentation, and clean-clone package verification are in place.
- [x] 2026-07-22T10:54:29Z — Checkpoint 8 complete: all 14 literal mandatory commands passed, three independent read-only reviews were resolved, machine evidence validated, and a root-only 20-file bootstrap review ZIP passed full detached hash validation before final clean-HEAD assembly.

## Decision log

- Use only ticket-sanctioned Python 3.13, uv, Hatchling, Pydantic v2, Typer, PyYAML, Ruff, mypy, pytest, Hypothesis, coverage, and build.
- Use a scheduled/manual Windows smoke workflow to conserve private-repository CI minutes.
- Install `DMFP-04_DATA_SOURCES_MARKETS_APIS_AND_LICENSING_ZERO_COST_v1.0.txt` only; the validator rejects any other DMFP-04 filename/version/hash.
- Use a detached review-manifest convention: the manifest hashes every ZIP member except itself; `SHA256SUMS` hashes all other members, including the manifest.
- Treat `pytest-cov` as the unavoidable development adapter implied by the mandatory `pytest --cov` acceptance command; it adds no runtime dependency and delegates measurement to the already sanctioned coverage.py.
- Include Hatchling in the locked development group as the sanctioned build backend so its exact resolved version and transitive build dependencies are captured in `uv.lock`.
- Pin the isolated build backend to uv-resolved Hatchling 1.31.0 and keep that exact version in the development lock, preventing build-environment drift.
- Bundle the single public-domain IANA tzdata 2025b `Europe/London` TZif payload with an enforced SHA-256 so stock Windows Python can validate the sanctioned default without an unapproved runtime dependency.
- Define `codex_result.review_pack.sha256` as the detached digest of stable primary review files 04-05 and 07-19; publish the separately validated final archive SHA-256 externally because an archive cannot contain its own digest.
- Read-only self-review found no authority/scope P0 issue and drove fixes for credential-shape leakage, CPU fallback coercion, fail-open scan coverage, PEM detection, missing-config doctor false health, Windows timezone portability, branch-metric reporting, clean-clone package provenance, evidence semantic checks, and atomic review placement.
## MIN-007R5F5 - final-output constraint scope remediation

- Ticket/stage: `MIN-007R5F5`, A7; required parent `94b561f427e18e6200acb892d44b99e1038a70eb`.
- Scope: remove transaction-wide `SET CONSTRAINTS ALL IMMEDIATE` from final publication.
- [x] Read and validate the remediation pack; verified branch, clean baseline, and Alembic head.
- [x] Scoped immediate validation to `trg_min007f_final_output_complete`, restoring it to deferred.
- [x] Added unit guard and one-outer-transaction A/B publication regression.
- [x] Ran all 22 acceptance commands; generated evidence and review archive.
## GCS-008 - goal and clean-sheet distributions

- Ticket/stage: `GCS-008`, A8; required parent `a5a0b66afd6e9645f971976d723e238824bee6a8`.
- Scope: one fixture's market-constrained joint team-score matrix and the coherent
  goal, outcome, total, BTTS and clean-sheet distributions derived from it.
- Constraints: preserve accepted Stage-7 mathematics, identities, persistence,
  replay resources, migrations, CLI and assurance; no live provider/network use,
  no player event allocation and no new dependency or Alembic revision.

### GCS-008 checkpoints

- [x] Reconciled DMFP-08 Stage-8 mathematics with the accepted repository and
  Stage-6/Stage-7 public contracts.
- [x] Implemented exact-Decimal independent-Poisson priors, adaptive support,
  deterministic soft-KL market projection, diagnostics and typed fallback.
- [x] Added strict Stage-7 identity/cutoff lineage, public schemas, immutable
  replay artifacts, CLI commands and realized-score evaluation.
- [x] Added unit, property, contract, golden, integration, adversarial, scope,
  coverage and installed-wheel assurance assets.
- [ ] Run every literal acceptance command from a complete clean checkout, bind
  evidence to measured exits and CI identities, and obtain independent/human
  acceptance before merge.

### GCS-008 decision log

- The canonical public object is one finite joint score matrix; all published
  marginals and market views are independently revalidated against that matrix.
- Stage 7 is consumed only as immutable home/away projection provenance and one
  cutoff. Stage 8 does not copy, refit or alter player-minutes probabilities.
- The production baseline uses uncertainty-weighted soft KL projection with
  market-family caps. Inconsistent markets remain visible as residuals instead
  of being silently repaired.
- Adaptive support must satisfy the configured tail bound; material overflow is
  a typed failure rather than silent renormalization.
- This vertical slice persists content-addressed JSON replay artifacts only. It
  deliberately adds no database table or migration.

## GCS-008 R1 - independent acceptance remediation

- Ticket/stage: `GCS-008 R1`, A8; required parent
  `668662a1c9a3f3a92d1c0305e6dfbf6b1d32a07a` on
  `stage/A8/GCS-008-goal-clean-sheet-distributions`.
- Scope: close only the six independent-review findings: Stage-6 outer-cutoff
  enforcement, matrix-derived market-fit validation, canonical Decimal public
  contracts, tracked baseline policy, fail-closed coverage input, and bounded
  scope validation.
- Constraints: preserve the accepted joint-score mathematics, Stage-7 binding,
  frozen probability outputs, Alembic head, dependency graph, and PR #2; no
  merge or self-acceptance.

### GCS-008 R1 checkpoints

- [x] Add focused mutation/regression tests for all six independent findings.
- [x] Implement the six narrow remediations and prove each reviewer reproduction.
- [x] Run combined GCS-008, static, repository, secret, scope, coverage, wheel,
  and PostgreSQL/Alembic gates.
- [x] Run one complete final-tree regression and refresh mechanical evidence.
- [ ] Create
  exactly one remediation commit, and push the existing PR branch.

# RUL-002R2 bounded PLAYER_POINTS interpretation approval

- [x] Verify the exact unapproved decision hash before mutation.
- [x] Bind the approved interpretation semantics and UTC human provenance to PLAYER_POINTS only.
- [x] Add approval-scope and arbitrary competition-ranking regressions.
- [x] Recompile ruleset and PLAYER_POINTS artifacts twice and independently verify new hashes.
- [x] Run targeted checks, the focused RUL-002 suite, static/security checks, then one complete repository regression on the final product tree.

# RUL-002R3 PLAYER_POINTS static-review remediation

- [x] Read the frozen remediation pack, DMFP-02 boundary requirements, and inspect the reviewed branch against the accepted main base.
- [x] Reconstruct the rules remediation on the accepted `origin/main` lineage while preserving the accepted Stage-9 interface.
- [x] Remove PLAYER_POINTS manager-state dependency leakage and add semantic closure guards.
- [x] Correct save/BPS and Stage-9 event/adaptation contracts, including non-GK save participation.
- [x] Implement versioned assist classification through the Stage-9 boundary and consistency governance.
- [x] Recompile deterministic artifacts, run focused gates, refresh governed evidence, and prepare the review result.

# RUL-002R4 Stage-9 versioned-assist allocation remediation

- [x] Confirm the reviewed R3 branch identity and read the controlling rules and Stage-9 boundary contracts.
- [x] Route generated target-v1.1 assist contexts through the compiled rules classifier for every supported goal mechanism.
- [x] Add generator/service/adapter regressions for penalty, free-kick, own-goal, ambiguity, determinism, and reconciliation.
- [x] Update non-GK-save limitation and PR handoff material without changing official rules data or activation state.
- [x] Run focused verification, preserve deterministic identities, refresh governed evidence, and prepare static rereview.

# RUL-002R1 target-season schema v1.1 and capability activation

- [x] Read the controlling DMFP-02 rules/model, provenance, ambiguity, schema-evolution, and activation requirements.
- [x] Add backward-compatible schema v1.1 authoring for capability verification, rule-level provenance, assist eligibility, additive save BPS, explicit removed events, participation semantics, manager-state transitions, and immutable interpretations.
- [x] Convert the captured 2026/27 PLAYER_POINTS families without discarding unresolved manager-state research.
- [x] Add compatibility, capability-closure, interpretation, and 2026/27 scoring regressions.
- [x] Compile and independently reproduce the PLAYER_POINTS capability hash; leave FULL_SEASON and global activation blocked.

# PTS-009-STATIC-FIX-R2 Stage-9 static acceptance remediation

- Ticket/stage: `PTS-009-STATIC-FIX-R2`, A9; pinned parent
  `43270ee54ceff6c4692a6a84118565c16fa6be72` on
  `stage/A9/PTS-009-static-acceptance-r2`.
- Scope: recover Stage-9 provenance, immutable Stage-7 participation binding,
  artifact replay/assurance, Gameweek lineage, confinement, and real-diff
  assurance without altering accepted rules, availability, or event code.
- Owner Scope Amendment 1 additionally permits only
  `evidence/tickets/GCS-008/current_manifest.json` as the mutable active
  repository snapshot. No PTS manifest, generator/validator change, or other
  scope expansion is authorized.

### PTS-009 R2 checkpoints

- [x] Verify pinned HEAD, branch, clean worktree, R2 pack integrity/context, and
  controlling Stage-2/7/9 authority.
- [x] Add mutation/regression coverage for F1-F6 and N01-N03 before or alongside
  the corresponding production repair.
- [x] Bind production to immutable Stage-2 activation evidence and preserve
  schema-v1.1 PLAYER_POINTS/assist behaviour.
- [x] Persist exact Stage-7 projections in participation requests; make event
  allocation preserve selected official minutes.
- [x] Regenerate fixture primitives and all derivations during independent
  artifact assurance; add Gameweek minutes/appearance/result lineage.
- [x] Constrain artifact paths and make scope assurance compare the actual Git
  worktree diff against this ticket declaration.
- [x] Run every literal acceptance gate, including PostgreSQL, migration, complete
  repository coverage, wheel isolation, final GCS-008 manifest validation, and
  secret scan; record only measured evidence.

# OPT-010 R3 independent final-rereview remediation

- Ticket/stage: `OPT-010`, A10; required base
  `a33f46cd7ec190fbd4959e2840527116f22547ac` on
  `stage/A10/OPT-010-one-gameweek-optimiser`.
- Scope: close the independent rereview's remaining Stage-9 lineage, frozen
  public-contract, legality-validation, artifact-confinement, oracle-fixture,
  and acceptance-evidence findings without changing Stage-10 objective or
  manager-tactics semantics.
- Acceptance: execute the existing 31 literal commands once, in order, on the
  final implementation revision. No reuse, sharding, or equivalence
  substitution is permitted.

### OPT-010 R3 checkpoints

- [x] Add adversarial regressions for detached Stage-9 identity, complete public
  result bindings, pre-search player-universe rejection, leaf-symlink attacks,
  and appearance-independent test data.
- [x] Align the public models and immutable hashes with the frozen Section 5
  contract while preserving deterministic exhaustive search.
- [x] Regenerate canonical request/result fixtures and pass focused static and
  behavioural checks.
- [ ] Commit the final implementation, run all 31 literal acceptance commands
  in order, and retain complete unsharded evidence.
- [ ] Regenerate the review pack, commit only evidence after the tested
  implementation revision, and push the existing draft PR branch.

# OPT-011 Stage-11 multi-Gameweek transfer optimisation

- Ticket/stage: `OPT-011`, DMFP-19 implementation Stage 11; immutable parent
  `49103e03bb1e7500aff5c15b90b136f2cc476405` from draft PR #7 branch
  `stage/A10/OPT-010-one-gameweek-optimiser`.
- Branch: `stage/A11/OPT-011-multi-gameweek-transfer-optimiser`.
- Scope: immutable manager state and ownership spells; configured integer sell/buy/bank/FT/hit
  transitions; deterministic multi-Gameweek scenario-tree search; node-indexed nonanticipative
  recourse; rolling current action; transparent terminal baseline; alternatives and interaction
  attribution; existing Stage-10 tactical adapter; deterministic CLI and evidence.
- Backend: no new solver dependency. The bounded exact enumerator is supported only for declared
  TEST/REPLAY trees, action sets and tactical candidates; PRODUCTION fails closed until an
  approved unrestricted backend and complete active transfer/price capability exist.
- Safety: no dependency, migration, provider, account-action, chip, rank/EO, price-prediction or
  target-season-rule inference; no merge or self-acceptance.

### OPT-011 checkpoints

- [x] Resolve and record the live PR #7 head branch/SHA without modifying Stage 10 or main.
- [x] Inspect repository authority, Stage-9/10 contracts, rules capability, CLI, tests, fixtures,
  assurance and dependency lock.
- [x] Implement typed manager-state, price, ownership-spell, bank, FT and hit transitions.
- [x] Implement validated scenario trees and exact nonanticipative bounded dynamic programme.
- [x] Reuse Stage-10 tactical evaluation through one explicit adapter.
- [x] Implement rolling advancement, terminal baseline, alternatives and bundle attribution.
- [x] Add supported CLI, adversarial fixtures, unit/property/oracle/integration tests.
- [x] Run focused and inherited validation, repair defects, benchmark, and record exact results.
- [ ] Build and independently assure `DMF_PULSE_STAGE11_SOL_REVIEW.zip` without merging.

# OPT-011 independent Sol review and remediation

- Review base: exact Stage-10 parent `49103e03bb1e7500aff5c15b90b136f2cc476405`;
  supplied implementation commit `9f1cdff6b6ad29d9d258013466105a65c5a257ec` reconstructed
  from the verified review patch.
- Remote safety: preserve pre-review Stage-11 export commit
  `dc2ed6ef4ca59e1946e7cc2814013aa317286ff0` as local
  `backup/stage11-pre-sol-review`; never modify or merge `main`.
- Acceptance: resolve every P0/P1, reach at least 90% meaningful Stage-11 branch coverage,
  run all achievable repository gates, refresh final-branch evidence, and push only a
  review-ready branch with human acceptance still pending.

### Independent review checkpoints

- [x] Verify bundle/member hashes, remote lineage, PR #7 parent identity, backup ref, clean
  reconstruction, expected changed-file inventory, and untouched 125-test baseline.
- [x] Independently audit authority, contracts, manager-state economics, scenario timing,
  nonanticipativity, tactical reuse, objective reconciliation, search truthfulness, hashes,
  artifacts, CLI execution, fixtures, and test-oracle independence.
- [x] Add adversarial regression/coverage tests and remediate every valid in-scope finding.
- [x] Run frozen sync, static checks, focused/inherited/full tests, branch coverage, build,
  installed-wheel CLI, benchmark, repository/artifact/scope validation, secret scan, and diff
  assurance; record exact results without upgrading unavailable gates to PASS.
- [x] Refresh OPT-011/stage evidence against the final code, perform hostile pre-push review,
  commit, push safely with lease protection if replacement is required, verify remote equality,
  and create or update the unmerged human-review PR.

# EVAL-012 Stage-12 backtesting framework

- Ticket/stage: `EVAL-012`, DMFP-19 Stage 12 / playbook B1; immutable parent
  `4f1274ccef419a7c0bde335c48bd4070e248b2e6` on `main`.
- Branch: `stage/A12/EVAL-012-backtesting-framework`.
- Scope: strict information sets/vintages; nested walk-forward/prequential folds; B0-B5;
  point/probability/distribution/joint metrics; calibration; stateful root-action replay; regret;
  leakage blocking; immutable reports/artifacts; offline CLI.
- Safety: synthetic acceptance only; no Stage 13+ models, paid history, provider access,
  production promotion, FPL execution, merge or self-acceptance.

## EVAL-012 checkpoints

- [x] Verify exact Stage-11 merge parent, repository authority and accepted interfaces.
- [x] Implement production evaluation contracts, metrics, replay, reports and CLI.
- [x] Add synthetic five-GW and ten adversarial leakage fixture families.
- [x] Run focused Stage-12 suite, branch coverage and offline vertical slice.
- [x] Record truthful limitations and create the self-contained Sol review bundle.
- [x] Complete fresh Sol review and remediation: close forecast-first, temporal, B0-B5,
  proper-scoring, scenario-weight, Stage-11 replay, artifact and reporting findings.
- [x] Pass the 104-test focused suite, 90% branch-aware coverage, canonical Ruff/mypy/build,
  installed-wheel six-command smoke, leakage canaries and dependency-relevant regressions.
- [x] Complete final repository/evidence assurance, push the review-ready branch and open the
  unmerged PR to `main`.
- [ ] Human acceptance, merge and accepted tag.

# RANK-015 Stage-15 rank-aware strategy

- Ticket/stage: `RANK-015`, DMFP-19 Stage 15; immutable parent
  `c53a1dfae952f481c1e885200ebf6120e4b63c24` on `main`.
- Branch: `stage/A15/RANK-015-rank-aware-strategy`.
- Scope: exact manager multipliers/EO; shared-scenario named mini-leagues; cutoff-safe
  probabilistic rival actions; epsilon/lexicographic rank utility; synthetic overall cohorts;
  accepted Stage-12/13/14 candidate re-evaluation; shared service and `dmf rank` CLI.
- Safety: raw projections remain invariant; only synthetic/approved/named-rival samples;
  early-season and invalid activation states fail closed to `PURE_POINTS`; no scraping, PR,
  merge, tag or human acceptance.

## RANK-015 checkpoints

- [x] 15.01 implement manager scenario multipliers, EO, leverage and chip/autosub effects.
- [x] 15.02 implement exact shared-scenario named mini-league ranking and exhaustive oracle.
- [x] 15.03 implement cutoff-safe probabilistic hidden rival action modelling.
- [x] 15.04 implement points-floor target/rank utilities and plan diagnostics.
- [x] 15.05 implement rights-gated synthetic weighted overall-rank cohorts.
- [x] 15.06 implement Stage-12/13/14 re-evaluation, fail-closed service, CLI and evidence.
- [x] Complete adversarial self-review, final Stage-15 validation and clean remote equality.

## RANK-015 independent Sol review

- [x] Verify exact pre-review remote lineage and immutable merge base.
- [x] Reconcile the supplied Stage-15 documents with repository-approved authority hashes.
- [x] Independently audit all six checkpoints, public contracts, oracles, gates, artifacts and CLI.
- [x] Remediate every valid P0/P1/material P2 with focused regression coverage.
- [x] Run the complete Stage-15 branch-coverage matrix and affected inherited regressions.
- [x] Run one bounded full-repository pytest attempt and all static/build/clean-wheel gates.
- [x] Publish truthful review evidence, verify final remote equality and open the unmerged draft PR.
