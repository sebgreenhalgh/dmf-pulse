# MIN-007C implementation plan

- Preserve the exact MIN-007B parent and frozen cutoff-safe dataset semantics.
- Add only a pure internal Decimal role-baseline model with authenticated policy/artifact lineage, regularised position priors, target-team temporal weighting, confidence metadata and the trusted hard-ineligibility override.
- Reuse the accepted MIN-007B history/training fixtures and add only the supplied synthetic role canary/policy fixtures needed by focused tests.
- Add unit, property and golden tests for the frozen artifact, all role canaries, mixed weighting, cutoff/team/window invariants, confidence caps and fail-closed validation.
- Record every literal acceptance command, make exactly one bounded commit, and verify a clean worktree.

Non-goals: minute PMFs, coherent lineup sampling, public coherent role marginals, persistence/migrations, CLI, evaluation/calibration, model registry, network/provider access, credentials and MIN-007A/MIN-007B redesign.
