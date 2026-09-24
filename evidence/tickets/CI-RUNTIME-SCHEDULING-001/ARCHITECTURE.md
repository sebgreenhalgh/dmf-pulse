# Phase 3 runtime-informed scheduling architecture

## Frozen selection boundary

- Parent: `8bb6e0f2e0b35f5976994fdc1fae9ffb94aa3712`.
- Selector: pytest collection with `-m "not performance"`.
- Eligible nodes: 5,300.
- Eligible-node digest before and after:
  `93303c8ea155f66831338f1e6cd854b1af2c9bb6deaab22fbdec5e075d4dc30e`.
- Timing data is read only after collection and can affect placement only.
- The four performance nodes remain in the separate blocking performance gate.

## Manifest and estimator

`config/testing/runtime_history.json` is canonical input to the planner. Its
schema, sources, bounded observations, estimates, fallback, and exceptional
partition policy are validated before use. The estimator prefers the maximum
of up to five recent measured samples; if a module has no measured sample it
uses the maximum labelled estimate. An unknown module uses
`max(2.0 seconds, 0.36 seconds * collected node count)`.

The bootstrap has 20 manifest modules: seven have exact isolated Phase-2 CI
observations and thirteen currently rely on calibrated Phase-2 local profiles.
The frozen collection has another 404 modules using the deterministic fallback.
Stale entries are harmless because collection remains authoritative.

## Evidence-backed partition exceptions

Whole-module placement remains the default. There are exactly two exceptions:

1. `test_team_strength_d3_seam.py`: the Phase-2 reuse experiment changed
   412.76s to 411.57s, while four independent calls remained 96.68-100.54s.
   Node partitioning therefore duplicates no material shared setup.
2. `test_team_strength_shadow_cases.py`: a Phase-3 isolated run completed in
   522.98s. The five calls were independently 84.06-92.65s and shared setup was
   83.23s. The conservative per-node estimate is 598.143s (setup plus average
   call, scaled by the already documented 3.5x CI/local calibration). This
   intentionally estimates bounded duplicated setup instead of dividing the
   old 1,604s module estimate blindly.

These exceptions preserve every existing node ID and assertion. They remove
the two 25-27 minute indivisible scheduling floors at an estimated 11.4%
aggregate-cost increase, which final CI must validate against wall-clock gain.

## Maintenance

`update-timings` consumes an explicit offline `ci-runtime-observations-v1`
artifact. It validates canonical in-repository module paths, rejects conflicts,
preserves unmentioned/stale entries, keeps the newest five samples per module,
and produces deterministic idempotent JSON. It never runs implicitly in CI.

Normal planning neither accesses the network nor writes the manifest. The
generated plan binds the manifest hash, Git SHA, eligible-node digest, plan
hash, per-shard assignments, per-module estimate kind and partition granularity,
and complete/disjoint partition proof.
