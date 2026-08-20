# RANK-015 Stage 15 progress

- Ticket: `RANK-015`
- Immutable parent: `c53a1dfae952f481c1e885200ebf6120e4b63c24`
- Branch: `stage/A15/RANK-015-rank-aware-strategy`
- Engineering status: `REVIEW_READY_PENDING_HUMAN_ACCEPTANCE`
- Production activation: `FAIL_CLOSED_TO_PURE_POINTS`
- Human acceptance: `false`
- Pull request: draft pending final publication
- Merge: none
- Accepted tag: none

## Non-negotiable invariants

- Rank strategy changes decision utility only. Raw football, minutes, price and FPL-points
  projections must remain hash-identical between points and rank modes.
- Sebastian and every represented opponent are scored from the same shared football scenario.
- Effective ownership is the weighted mean counted manager multiplier, never raw ownership.
- Rival future actions are cutoff-safe probabilistic scenarios, not perfect Pulse clones.
- Rank-aware activation fails closed when rules, target, rights, cohort, opponent or confidence
  gates are invalid.
- Only synthetic, repository-approved or authorised named-rival data are permitted; no mass
  manager scraping or final-rank hindsight cohorts.

## Baseline

- Immutable parent verified against `origin/main` before branch creation.
- Branch was created directly from the immutable parent and pushed before implementation.
- Accepted Stage-14 targeted matrix: `399 passed in 10.21s`.
- No Stage-15 `rank_strategy` package or `dmf rank` CLI existed at the parent.
- A temporary branch-only source-export workflow was required because the execution container
  could not resolve GitHub. It was removed from the final review tree before handoff.

## Checkpoints

| Checkpoint | Status | Capability SHA | Verification |
|---|---|---|---|
| 15.01 manager multipliers / EO | COMPLETE / REMOTE | `77f2cd2c57649a224bc7908128163b498d5b8bd5` | `39 passed`; 99% branch coverage; 11 inherited passed |
| 15.02 exact named mini-league | COMPLETE / REMOTE | `bf0ebb29e9af4f33f4a9575222da61021c9df748` | `53 passed`; 95% branch coverage; exact 2/3/4-manager oracle PASS |
| 15.03 baseline opponent model | COMPLETE / REMOTE | `a5b3e2a5f852dbde1f5b3ca4c8a91b1f60694868` | `123 passed`; 95.92% branch coverage; 11 inherited passed |
| 15.04 target / rank utility | COMPLETE / REMOTE | `bc03b1f7b020835b2b36896cc39d58a84b8808a4` | `127 passed`; 92.13% branch coverage; projection invariance and fail-closed gates PASS |
| 15.05 synthetic overall cohort | COMPLETE / REMOTE | `62f1828edcfbd0569dbf76fc93e241f2db95094d` | `23 passed` at publication; exact independent synthetic-field oracle PASS |
| 15.06 service / CLI / evidence | COMPLETE / REMOTE | `c77b8950a4a150407b51d9bfed69b2314c74380e` | `243 passed`; raw branch coverage `91.334895%`; service/CLI/artifacts PASS |

## Required final status

`REVIEW_READY_PENDING_HUMAN_ACCEPTANCE`

`FULL_REPOSITORY_PYTEST = RESOURCE_LIMIT`

## Independent Sol review

- Exact pre-review and actual starting remote SHA:
  `17b6aa576459c652e14015dcfd7b7cf0bffd6f9d`.
- Immutable parent and merge base: `c53a1dfae952f481c1e885200ebf6120e4b63c24`.
- Remediation commits published during review: `bb9443c`, `f457342`, and `af7c467`.
- Findings: zero P0; seven P1 fixed; three material P2 fixed; zero P3.
- Regression expansion: 31 parameter-expanded test cases, with additional strengthened assertions.
- Final Stage-15 matrix: `274 passed in 11.19s`.
- Raw branch coverage: `861/954 = 90.251572327044%`.
- Targeted inherited Rules and Stages 9-14 matrix: `37 passed in 5.41s`.
- Projection invariance, common football worlds, EO, independent mini-league oracle,
  independent synthetic-field oracle, nonanticipativity, rank-PMF reconciliation,
  service fallback and artifact tamper rejection: PASS.
- One bounded full-repository pytest attempt: `RESOURCE_LIMIT`; exit `124` after
  `1204.026s`, with no emitted failure and no unchanged-suite rerun.
- Frozen sync, Ruff, strict mypy, build and clean installed-wheel CLI: PASS.
- Governed manifest refresh, repository validation and first-party secret scan: PASS with zero
  errors/findings.
- Current main remained the immutable parent: `NO_MAIN_INTEGRATION_REQUIRED`.
- Independent verdict: `PASS_WITH_NONBLOCKING_LIMITATIONS`.
- Human acceptance, merge and accepted tag remain pending.

## Checkpoint 15.01 evidence

- Implemented exact scenario multipliers using the accepted Stage-10 autosub/captain evaluator.
- Supported ordinary captain, conditional vice fallback, Triple Captain, Bench Boost and Free Hit.
- Free Hit uses the temporary squad without mutating the permanent squad; transfer hits are deducted once.
- EO is the normalised weighted mean scenario multiplier and can exceed 100%; raw ownership remains separate.
- Exposed saved/scenario EO, action ownership, intervals and Sebastian leverage.
- Rights-invalid samples fail before numerical use.
- Focused Stage-15 matrix: `39 passed in 0.63s`.
- Stage-15 branch coverage at checkpoint: `99%` (`341 statements`, branch-aware).
- Inherited accepted-interface regressions: `11 passed` across Stage-10 autosub/oracle and Stage-14 captain/TC/BB/FH semantics.
- Ruff focused: PASS. Strict mypy for `src/dmf_pulse/rank_strategy`: PASS.
- Raw projection hash remained identical before and after EO evaluation.
- Fetch-back verification found six connector-introduced quoted annotations; Ruff caught them and capability SHA `77f2cd2c57649a224bc7908128163b498d5b8bd5` is the corrected checkpoint.

## Checkpoint 15.02 evidence

- Implemented exact classic mini-league rank simulation for two, three and arbitrary multi-manager leagues.
- Every manager is evaluated on identical Stage-9 scenario and outcome-draw identities; mismatched raw projections, weights or scenario hashes fail closed.
- Final score reconciles cumulative points, shared-scenario Gameweek net points and one hit deduction.
- Verified active tie policy: points primary, then fewer counted transfers; exact equals share competition rank; Wildcard and Free Hit transfers are excluded by the supplied counted-transfer state.
- Exposed exact outcome standings, shared-rank flags, winners, rank PMF, expected/median/percentile rank, P(target) and mini-league win probability.
- Independent exhaustive oracle imports no production mini-league/rank implementation and matches exact two-, three- and four-manager fixtures.
- Focused Stage-15 matrix after exact GitHub fetch-back: `53 passed in 1.22s`.
- Stage-15 branch coverage at checkpoint: `95.24%` (`507 statements`, branch-aware).
- Inherited accepted-interface regressions: `11 passed in 1.98s`.
- Ruff focused: PASS. Strict mypy for `src/dmf_pulse/rank_strategy`: PASS.
- Exact local/remote checkpoint SHA equality: `bf0ebb29e9af4f33f4a9575222da61021c9df748`.

## Checkpoint 15.03 evidence

- Implemented an explicit random-utility opponent action model over exact legal rival plans.
- Supports no-transfer, transfers and hits, captain/vice changes, Triple Captain, Bench Boost, Free Hit and Wildcard branches.
- Probability vectors are positive, normalised, entropy-reconciled and non-degenerate; profiles explicitly prohibit perfect-rationality assumptions.
- Rights, manager identity, cumulative points, counted-transfer state, squad semantics, feature timing and postdeadline action labels fail closed at the service boundary.
- Free Hit and Wildcard transfers do not enter counted-transfer tie state; ordinary transfers do exactly.
- Exact multi-rival joint distributions preserve every marginal and expose the baseline conditional-independence assumption.
- Hidden rival plans are scored against identical Stage-9 scenario IDs, outcome draw IDs, weights, scenario-set hashes and raw-projection hashes.
- Focused Stage-15 matrix: `123 passed in 5.78s`.
- Stage-15 branch coverage: `95.92%` (`1194 statements`, branch-aware).
- Inherited accepted-interface regressions: `11 passed in 1.59s`.
- Ruff focused: PASS. Strict mypy for `src/dmf_pulse/rank_strategy`: PASS.
- Remote source blob hashes for the opponent contracts/service matched the tested local files; stale transport request was removed before checkpoint sealing.

## Checkpoint 15.04 evidence

- Preserved both the points-optimal and rank-optimal plans and selected rank utility only through explicit lexicographic/epsilon policy; no weighted points/rank sum was introduced.
- Implemented PURE_POINTS, MEASURED_LEVERAGE, TARGET_RANK, RANK_PROTECTION, MINI_LEAGUE_WIN, RANK_BAND and PRIZE_BAND evaluation surfaces.
- Re-derived expected rank, P(target) and mini-league win probability from the sealed rank PMF and rejected noncanonical, unnormalised or out-of-population PMFs.
- Enforced the configured expected-points floor, measured expected-points sacrifice and target-probability gain, and retained template beta, tracking error and confidence diagnostics.
- Added explicit selected-target activation, candidate-level confidence and semantic scenario-score hash gates; post-validation mutation and invalid target surfaces fail closed to PURE_POINTS.
- Early season defaults to PURE_POINTS; being behind does not force variance, being ahead does not force template matching, and ownership alone has no positive or negative utility.
- Projection-invariance evidence proves the common raw-projection hash and scenario-set hash are unchanged across points and rank modes.
- Corrected two genuine inherited defects exposed by the resumed work: future-feature leakage was masked by future-action validation order, and several tests mutated serialised dictionaries as if they were Pydantic models. Regression tests now preserve distinct temporal diagnostics.
- Focused Stage-15 matrix: `127 passed in 2.18s`.
- Checkpoint-scoped Stage-15 branch coverage: `92.13%`; the deliberately unfinished 15.05 synthetic module was excluded from this checkpoint-only denominator.
- Ruff focused: PASS. Strict mypy for `src/dmf_pulse/rank_strategy`: PASS. `git diff --check`: PASS.
- Exact local/remote sealed capability SHA equality: `bc03b1f7b020835b2b36896cc39d58a84b8808a4`.


## Checkpoint 15.05 evidence

- Implemented the real weighted synthetic overall-field simulator with explicit integer populations and rank bands.
- Reconciles cumulative points, Gameweek net points, counted-transfer tie state, weighted rank PMF, expected/percentile rank and P(target).
- Exposes concentration, entropy, maximum-share and effective-representative diagnostics with explicit known-truth/approximation status.
- Carries rights, provenance, source-bundle and upstream hash lineage; mass scraping, final-rank hindsight and definitive overall-win claims are prohibited by literal contracts.
- Independent exhaustive oracle imports no production synthetic simulator and matches the known-truth field exactly.
- Published capability SHA: `62f1828edcfbd0569dbf76fc93e241f2db95094d`.
- Original focused publication matrix: `23 passed`. Hardened current synthetic matrix: `34 passed`; raw branch coverage `98.684211%`.

## Checkpoint 15.06 sealed evidence

- Implemented shared Stage-15 service over sealed accepted Stage-12/13/14 candidate identities without invoking or duplicating upstream optimisers.
- Preserves points-optimal, rank-optimal and selected plans, expected-points/target-probability deltas, raw/scenario identities, rank diagnostics, confidence and fail-closed reasons.
- Binds Stage-9 through Stage-15 component lineage, cutoff, rules, rights, points-floor, code and config versions.
- Added complete required-gate inventory and pure-points fallback for rules, target, rights, cohort, opponent, confidence, projection/scenario lineage, points floor and early-season policy.
- Added immutable Stage-15 artifacts using canonical detached hashes and recomputation on load; nested or outer tampering fails closed.
- Added real `dmf rank` validate/eo/mini-league/opponents/cohort/evaluate/compare commands through the shared service.
- Current complete Stage-15 matrix: `243 passed in 15.85s`.
- Raw Stage-15 branch coverage: `91.334895%` (`780/854`); combined line/branch coverage: `95.192007%`.
- Ruff format/lint: PASS. Strict mypy: PASS. `git diff --check`: PASS.
- Product implementation is sealed for independent review; no human acceptance is recorded.

## Final Stage 15 implementation evidence

- Status after independent Sol review: `REVIEW_READY_PENDING_HUMAN_ACCEPTANCE`.
- Actual finalisation starting remote SHA: `0a16ebaf6376c2347845ae9bb7804433fe6823e4`.
- Immutable main: `c53a1dfae952f481c1e885200ebf6120e4b63c24`.
- Checkpoint 15.05 capability: `62f1828edcfbd0569dbf76fc93e241f2db95094d`.
- Checkpoint 15.06 capability: `c77b8950a4a150407b51d9bfed69b2314c74380e`.
- Complete Stage-15 suite: `243 passed`.
- Raw branch coverage: `91.334895%` (`780/854` branches); combined coverage `95.192007%`.
- Targeted inherited rules and Stages 9–14 regressions: `37 passed`.
- Projection invariance and shared-football-scenario invariant: PASS.
- Exact mini-league oracle and independent exact synthetic-field oracle: PASS.
- Nonanticipativity, future-action leakage and final-rank-hindsight exclusions: PASS.
- Rank-aware activation failures preserve and select `PURE_POINTS`: PASS.
- Service/CLI semantic equivalence and artifact tamper rejection: PASS.
- Frozen dependency sync at the starting remote SHA: PASS in the successful GitHub validation/export runs; the final local run reused the exact exported environment because this container has no external DNS.
- Ruff format/lint, strict mypy, repository validation, secret scan, Hatchling sdist/wheel build and clean external-wheel CLI: PASS.
- Temporary Stage-15 workflows and `recovery/stage1505`, `recovery/stage1506`: REMOVED.
- `FULL_REPOSITORY_PYTEST = RESOURCE_LIMIT` after the single bounded independent attempt.
- PR / merge / tag / human acceptance: none.
