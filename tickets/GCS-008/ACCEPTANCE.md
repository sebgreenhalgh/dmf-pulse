# GCS-008 acceptance contract

This file defines gates. It does not assert that they passed.

## Scope and parent

- The implementation branch descends from `a5a0b66afd6e9645f971976d723e238824bee6a8`.
- `scripts/validate_gcs008_scope.py` passes from the real Git diff.
- No Stage-7 source, migration, dependency lock, or unrelated module is changed.
- `IMPLEMENTATION_PLAN.md` contains the reconciled GCS-008 execution plan and exact file map.

## Static quality

- `uv sync --all-groups --frozen`
- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run mypy src/dmf_pulse`
- `git diff --check`

## Semantic tests

- Unit tests cover Poisson PMFs, adaptive support, market rows, family caps, KL projection, exact derivations, fallbacks, persistence, cutoff checks, and identity mutation.
- Property tests cover nonnegative exact simplexes, clean-sheet and expectation identities, binary complements, support stability, determinism, and invalid probabilities.
- Contract tests validate the accepted Stage-6 and Stage-7 public boundaries and frozen public JSON schemas.
- Golden tests compare the complete balanced-fixture artifact and result hash.
- Integration tests cover Stage-6 consensus, missing/inconsistent markets, immutable persistence, cache invalidation, CLI exits, and evaluation.
- Adversarial tests reject post-cutoff markets/minutes, impossible market states, binary floats, NaN/Infinity, malformed hashes, output mutation, unsupported market support, and artifact conflicts.

## Numerical acceptance

- The public matrix is nonnegative and sums exactly to one.
- Public PMFs and all binary distributions sum exactly to one.
- Home clean sheet equals `P(away goals = 0)` and away clean sheet equals `P(home goals = 0)`.
- Expected goals equal the corresponding public PMF expectation at the declared scale.
- Every 1X2, total, BTTS, and scoreline output is recomputed from the same matrix.
- The omitted prior tail is below policy tolerance and remains visible.
- High-trust feasible synthetic constraints are reproduced within `1e-9`.
- Inconsistent evidence remains a proper soft projection with measurable residuals.

## Identity and replay acceptance

- The complete Stage-7 identity context is published and its semantic hash independently recomputes.
- Stage-7 fixture/team/cutoff/result mutation changes or invalidates the Stage-8 identity.
- Market, prior, policy, fixture/team, or cutoff mutation changes the input signature and result identity.
- Repeated runs are byte-for-byte deterministic.
- Content-addressed persistence reuses identical bytes and refuses conflicting bytes.

## Packaging and repository gates

- Repository-wide pytest and branch coverage pass.
- GCS-008 critical modules meet the ticket statement/branch thresholds.
- Packaged policy and schemas equal repository copies and runtime models.
- `uv build` passes.
- `scripts/verify_gcs008_wheel.py` passes outside the source tree.
- The inherited disposable-PostgreSQL migration matrix and integration suite pass even though GCS-008 adds no migration.
- Repository validation, secret scan, evidence validation, independent review, and human acceptance complete.

Run `ACCEPTANCE_COMMANDS.ps1` literally from a clean checkout. Only raw command exits and CI identities can establish PASS.
