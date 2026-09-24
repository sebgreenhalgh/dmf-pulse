# Phase 3 adversarial self-review

Status before exact-SHA CI: no unresolved P0, P1, or material P2 finding.

1. Timing data cannot omit a test. Pytest collection occurs first and the plan
   validates the exact union, duplicates, omissions, and unexpected nodes.
2. Malformed history fails closed before placement. It cannot reduce selection.
3. Unknown modules receive the deterministic documented fallback. A wholly
   absent/unreadable manifest is a hard failure rather than silent guessing.
4. Two independent plans from the same parent, collection, manifest, and shard
   count were byte-identical (`SHA256 00F7B34DA062FF2D09688613353392D81F909636D54B535AEF914D43125B19D1`).
5. Estimates are committed observations or the one documented fallback formula.
   Source kind distinguishes exact measurement from calibrated estimate.
6. The 53-entry Python table is removed, not renamed. Twenty entries were
   replaced by observed data and 33 obsolete hints now use the generic fallback.
7. Path normalization rejects absolute paths, traversal, noncanonical separators,
   non-test paths, control characters, and updater paths absent from the repository.
8. Stale manifest modules do not affect collection. Updater retention is explicit.
9. New modules plan successfully through fallback and appear in unknown counts.
10. The non-performance node count and digest are exactly Phase 2's 5,300 and
    `93303c8e...30e`; the four-node performance collection remains blocking.
11. Fast cadence remains 2,117 nodes with digest `d892e3e4...95af`.
12. No file below `src/dmf_pulse/` is changed.
13. The 90% coverage gate, branch transport/proof, artifact completeness, and
    exact-SHA binding are unchanged. Exact CI remains required to prove the result.
14. Maintenance is reduced to a strict bounded JSON history and explicit updater.
15. Estimated imbalance improves from 3.590777x to 1.167246x. Real wall-clock
    causality must be judged from final CI, not inferred from the estimate.

## Material trade-off reviewed

The two node-partition exceptions increase estimated aggregate test work from
12,157.18s to 13,543.895s (+11.4%) because the five canonical shadow cases repeat
an 83.23s local immutable preparation. This is deliberate and visible. It removes
the measured 26m44s and 25m04s indivisible floors without changing test semantics,
and keeps the predicted aggregate close to Phase 2's realised 13,581s. If exact
CI does not materially reduce the critical path, the shadow-case exception is the
first rollback candidate; the generic runtime-manifest architecture remains valid.

## Non-blocking debt

- Generic coverage remains coupled to historical GCS-008 names and evidence paths.
- Thirteen manifest modules currently use labelled calibrated local estimates;
  future exact isolated CI observations should replace them through the updater.
- This review was performed in an isolated clean-worktree pass by the implementing
  agent. No separate human acceptance or merge is claimed.
