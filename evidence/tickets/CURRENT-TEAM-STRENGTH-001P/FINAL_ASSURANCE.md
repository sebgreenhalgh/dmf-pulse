# CURRENT-TEAM-STRENGTH-001P final implementation assurance

## Lineage and resumability

Branch: `readiness/CURRENT-TEAM-STRENGTH-001P-private-three-gw-shadow`.
Private base: `f39ba4ee3ea748cf60c5743e48f7f68cc6784a71`.
Public source: `6b96f5b85692fb3ec368ee261ad93a554128e017`.
Common base: `99418f3316277f4dae347d80358d5dd5a09655b2`.

The eight original and cherry-picked commit pairs are authenticated in
`lineage_integration.json`. All 87 public-owned files remain exact, including model
maths, public contracts, governance, rights, identity and replay. Final private
scope proof is `final_lineage_preservation.json`.

Published checkpoints:

- .01: `797d143a2b3a1ba4698cc6f70b789ddf3e3ab66a`
- .02: `3ed03170a8b73d4ec1d4b9f7675cba63a0e26be5`
- .03: `425db35615aa6992522ddba154796f748925c751`
- .04: `d091f201679cc9e77fafcc19dcec8cd18b11b82a`

The final commit containing this evidence must be checked against origin and its
exact-SHA mandatory CI jobs before handoff. That post-publication result is reported
in the final handoff, not fabricated inside its own commit. Earlier checkpoint CI
runs may be cancelled by the repository's existing branch concurrency policy.

## Preserved public 001A evidence

- Model: `10335a94d4466f487eac92d86325d5d2dc66a8813ae872fd907f131f5c22281b`.
- Identity: `55f36445b0aabc77add11560e3ea550cbc07ec114db48dbf664e7177c65331ef`.
- Governance: `e8d28521fcb90b625a8dbeff4f72de3b178d16ed7cae748a7429d0e42cdd9fd7`.
- Dataset: `b4de6ce2e4ab1c0e6b7e766ac1de3e60ed539593e13b24f805a0e68cfd6e7c51`.
- Reconstructed 2025/26 holdout baseline: 2.9519886029949367; governed D+2
  candidate: 2.887749425936601; delta: -0.0642391770583357.

The actual retained-corpus replay and external public installed wheel passed at
.01. No source reacquisition or policy retuning occurred. Half-life 365, priors
12/12, historical entrant cohort, global home effect, effect coding, Newton fitting,
rate bounds, covariance and shadow limitations are unchanged.

## Private architecture and baseline purity

The explicit comparison consumes one frozen `_PrivateV1PreparedRollingContext`.
It authenticates an all-fixture private binding to the unchanged public model and
fixture bundles. The public P0 UUIDv7 identities remain separate from private
fixture/team identities, connected only by the sealed season-scoped FPL-ID crosswalk.
No new identity, fuzzy rematching, or public-contract relaxation exists.

`LEAGUE_BASELINE` constructs `PrivateV1RollingRecommendationService()` literally.
`TEAM_STRENGTH_SHADOW` constructs a fresh service with the private prior resolver.
The underlying sealed baseline execution is not mutated. The shadow lineage binds
its separate authenticated combined input. All fixtures are substituted or the
whole world is unavailable. Hard integrity/cutoff failures propagate, not fallback.

Both worlds use the literal ordinary stale player allocation, with no R9C allocation
resolver. Current-model Stage-7 projections must already exist; manual reconstruction
is rejected. Actual tests observe one fit and 18 predictions during preparation,
then zero fit/predict/provider work during the two solves.

The cross-build regression against f39 passes for full ordinary execution content,
decisions, reports, projections and optimiser outputs. The existing market code
identity hashes the whole Python package, so each build reconstructs its genuine
market evidence. Only propagated hash strings and bijective GW information-set IDs
are normalised in the diagnostic. This is semantic equality, not false byte identity.
Ordinary `dmf pulse`, one-command construction, Stage-8 maths, R9B, points and
optimisation implementation remain unchanged. No dependency change or DB requirement.

## Controls, cases and performance

Twenty-four mandatory authenticated controls cover frozen source/cutoff/fixture
order, Stage 7, allocation/fallbacks, markets, manager/ownership/prices, rules,
randomness/scenario policies, exact accelerator, candidate policy, work budget,
terminal/future-price/chip policy and algorithm build. Actual Stage-8 request bodies
are identical except priors. Actual scoreline seed/namespace/index/integer draws
are equal; different sampled outcomes are legitimate. Both real canonical Stage-11
solves produce nonzero legal-action counts.

Five locked one-draw synthetic cases pass; see `CHECKPOINT_04.md` and the explicit
`synthetic_cases.json` report. The latter retains safe aggregate summaries, every
fixture prior/market/Stage-8 hash, both complete synthetic decision signatures,
control hashes and nonsemantic timings. It never changes golden expectations.
These cases do not demonstrate live calibration or prospective model value.

Performance reports separate preparation, baseline/shadow projection, baseline/shadow
solve and comparison overhead. They are observed offline concurrent-load diagnostics,
not a changed optimiser policy or claimed production service-level bound.

Observed fixed-case run (seconds; common preparation 110.275):

| Case | Baseline projection | Baseline solve | Shadow projection | Shadow solve | Comparison overhead |
|---|---:|---:|---:|---:|---:|
| A | 39.500 | 0.218 | 40.886 | 0.214 | 24.147 |
| B | 39.507 | 0.230 | 43.551 | 0.219 | 25.390 |
| C | 39.167 | 0.219 | 42.278 | 0.223 | 24.696 |
| D | 37.574 | 0.213 | 42.633 | 0.213 | 23.738 |
| E | 38.862 | 0.747 | 43.263 | 0.258 | 23.868 |

## Acceptance and review

Recorded commands/results are in checkpoint .01 through .04 and the JSON proofs.
Principal completed populations: 787 inherited tests, 92 bounded inherited tests,
64 fresh direct tests and five real materiality cases. Fresh direct coverage is
484/484 statements and 124/124 branches, with zero exclusions. Real pipeline
tests also inspect error, divergence, tamper, unavailable and mutation paths.

Ruff format/check and strict mypy pass (307 production files). Frozen offline sync,
wheel/sdist build and clean external runtime-only installed comparison pass. The
wheel test runs the real B case, not an import-only check. Both current manifests,
repository validator, first-party secret scan and diff check pass. Inherited CI
retains its PostgreSQL requirement; 001P adds none. Only static module-weight hints
were added to balance the expensive tests; selection, thresholds, timeouts and
mandatory gates were not weakened.

Adversarial self-review hardened required control inventory, nested resealed-report
reconciliation, current-cutoff source assessment and no-recompute Stage-7 guards.
Fresh independent whole-ticket review found no unresolved P0/P1/material P2:
`CLEAR_FOR_TEAM_STRENGTH_001P_ONE_SHOT_LIVE_OBSERVATION`.
See `FINAL_INDEPENDENT_REVIEW.md`. This is not authorization to execute providers.

The legacy generic review-pack builder has no 001P contract and correctly rejected
that ticket. The ticket-specific builder follows the accepted capped/hash-verified
archive pattern without changing the legacy assurance module. It includes only
source and synthetic ticket evidence, caps each entry at 2MiB and total payload at
8MiB, and verifies every archived entry hash. Output remains under ignored review_pack.

## Activation and disclosure

TEAM_STRENGTH_001A_INTEGRATED_IN_PRIVATE_LINEAGE

LEAGUE_BASELINE_REMAINS_LITERAL_DEFAULT

TEAM_STRENGTH_REMAINS_SHADOW_ONLY

SCORE_PRIOR_IS_THE_ONLY_INTENDED_MODEL_ABLATION

STAGE7_IDENTICAL_ACROSS_PRIOR_WORLDS

PLAYER_ALLOCATION_IDENTICAL_ACROSS_PRIOR_WORLDS

MARKET_CONSTRAINTS_IDENTICAL_ACROSS_PRIOR_WORLDS

COMMON_RANDOM_NUMBERS_USED

REAL_CANONICAL_STAGE11_SOLVES_USED

NORMAL_DMF_PULSE_PATH_UNCHANGED

NO_LIVE_PROVIDER_ACTION_PERFORMED

NO_PRIVATE_LIVE_DATA_PERSISTED

NO_PRODUCTION_ACTIVATION_PERFORMED

No credential inspection, A2 execution, one-shot approval consumption, PR, merge,
accepted tag, parameter mixture or automatic live observation occurred. The original
dirty user checkout remains untouched; cleanliness applies to the isolated worktree.
