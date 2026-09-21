# Adversarial implementation self-review

Review scope: exact P0 parent through checkpoint .04 plus final validation/error-path tests.
This is not human acceptance or production promotion. Final command gates and independent
whole-ticket review are recorded separately; running gates are not claimed as passed here.

- Statistical: home eta = mu + global_home + attack_home - defence_away; away eta = mu +
  attack_away - defence_home. Both effect vectors reconstruct their final component as minus
  the sum of N-1 free coordinates throughout optimization. Mu/home are not penalized.
  Main kappa is 12 times the unweighted two-score mean, matching the recovered script.
  Prior-season entrants use complete-season unweighted neutral 4/4 auxiliary fits; current
  entrants cannot contribute their first-season results. Main decay includes off-season days.
- Numerical: finite-difference derivative tests, inverse-information product, synthetic
  ordering/home recovery, sparse entrant, high-score and all-zero histories, SPD failures,
  line-search exhaustion and 100-iteration failure are explicit. No pseudo-inverse, jitter,
  clipping, hidden scientific dependency or operator hyperparameter knob. Both stopping
  criteria are mandatory. The eight-ulp line-search allowance never relaxes final criteria.
- Temporal/source: real receipt/validation/usable provenance is preserved; reconstructed
  cutoffs do not imply historical availability. D+2 applies to all governed fits. Missing
  due fixtures and unknown status block new artifacts. The latest sealed model may be reused
  only with explicit degraded status and authenticated source reassessment. No repository
  commit-age freshness proxy exists. Source/fixture mappings are exact P0 UUID identities.
- Authentication: nested content hashes plus expected immutable identities are validated.
  Cached validation keys use full serialized bytes; public preparation cannot mutate cached
  validated state. Resealed contradictory source/model/bundle/replay contracts are rejected.
  Stable model state and timestamped execution envelope have separate semantic identities.
  Private persistence is content-addressed and exclusive, with collision/path/race tests.
- Rights/security: exact distinct team-strength profile and capability/config identity;
  existing static league profile unchanged. Existing pinned-host transport is reused. No
  credentials, FPL/Odds inputs or network in deterministic tests/replay. Public output contains
  summaries only. Raw retained corpus, fixture registry, coefficients and per-fixture output
  remain private. A linked-worktree sdist leak was detected before publication and closed by
  explicit exclusion plus archive inspection; no affected archive was published.
- Stage 8/architecture: existing ScorePriorRequest and Stage-8 math/schema unchanged. Real
  prior-only and inherited balanced-market projection tests pass. The inherited HDA-only
  non-convergence case is explicitly tested as degraded fallback, not projection success.
  No private-v1/ordinary recommendation path, league-prior replacement or mixture prediction.
- Evaluation: fixed 2025/26 holdout and time-valid 2022/23–2024/25 baseline. Original-research
  date predicate is metrics-only and distinct from governed D+2 (one origin differs). Same
  normalized 0..36 support and recovered secondary definitions. Predeclared 2e-6 research
  tolerance and separately pinned 1e-9 golden metric tolerance; no automatic golden updates.
  2026/27 is excluded from policy selection. No claim of live-vintage OOT evidence.

Known limitations: local asymptotic penalized covariance excludes family, selected-policy
and source uncertainty; plug-in predictions remain shadow only. Parameter mixture is not
propagated. CURRENT-TEAM-STRENGTH-001U is mandatory before any production promotion.

No unresolved implementation defect identified by this self-review. Coverage, final inherited
acceptance, a fresh independent review and final exact-SHA CI remain separate blocking gates.

Post-review closure: the fresh independent review found three issues omitted above: LIVE
midnight due-completeness advancement, aware-offset normalization before semantic hashing,
and the evaluation scope label. All were remediated and independently verified; see
INDEPENDENT_REVIEW.md. The model coefficients, original/governed replay metrics and golden
identity are unchanged. Final actual branch coverage is 95.9799% with zero exclusions.
