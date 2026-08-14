# GCS-008 implementation result

## Status

A complete repository-relative Stage-8 implementation artifact, including a delivery-only patch for the existing `PLANS.md`, has been generated for `stage/A8/GCS-008-goal-clean-sheet-distributions`, based on required parent `a5a0b66afd6e9645f971976d723e238824bee6a8`.

The complete 3,513-line `08_FOOTBALL_EVENT_DISTRIBUTION_ENGINE(6).txt` specification (SHA-256 `7cb378f26741d28e6b900530102dfdbd2286470c5b8920764792eb70834c18ff`) and the accepted parent/live repository contracts were inspected through the connected GitHub repository. The requested implementation branch was verified to point exactly at the required parent and was not modified by this artifact-generation run. `main` has not been modified.

## Implemented

- Exact-Decimal independent-Poisson home/away score prior.
- Adaptive score support with explicit omitted-tail diagnostics and fail-closed maximum support.
- Typed score-grid events for 1X2, totals, team totals, clean sheets, BTTS, and exact scores.
- Strict accepted Stage-6 `MarketConsensus`/`MarketNormalisationResult` request union, including fixture, cutoff, bounds, disagreement, freshness, operator lineage, and semantic-hash validation.
- Read-only Stage-7 home/away projection identity contract with fixture/team/cutoff validation and replay-hash binding; no Stage-7 formula or public contract was altered.
- Market-family weight caps and deterministic uncertainty-weighted soft KL projection.
- Visible typed prior fallback only when the immutable policy permits it.
- Canonical `joint-score-distribution-v1` containing the matrix, goal PMFs, goals-conceded PMFs, expected goals, 1X2, totals, BTTS, clean sheets, scorelines, residuals, diagnostics, confidence, and complete lineage.
- Independent coherence validation and canonical SHA-256 identities.
- Atomic content-addressed JSON persistence with identity-conflict rejection.
- Offline Typer commands for projection, market-fit explanation, validation, and realized-score evaluation.
- Public request/result/distribution JSON schemas in repository contracts and packaged resources.
- Proper-score evaluation for exact score, team goals, 1X2, clean sheets, and BTTS.
- Synthetic TEST/REPLAY fixtures, a checksum manifest, reviewed golden output, scope/coverage/acceptance validators, and installed-wheel verification.
- Unit, property, contract, golden, integration, and adversarial tests.
- Linux CI and Windows smoke additions.

## Deliberately unchanged

- Accepted Stage-7 algorithms, public models, persistence, packaged replay resources, migration, CLI, and assurance machinery.
- Accepted Stage-6 normalization mathematics and persistence.
- Alembic head `20260807_0006`.
- `pyproject.toml`, `uv.lock`, `pylock.toml`, and the dependency set.
- `main`.

## Actually executed in this implementation environment

The following results were measured under Python 3.13.5 against the generated Stage-8 tree. A temporary local Stage-6 public-model overlay was used solely because the full parent checkout was not mounted in the execution filesystem. These measurements do not replace clean-checkout repository CI.

1. Python syntax compilation:

   ```text
   PYTHONPATH=src python -m compileall -q src tests scripts
   PASS
   ```

2. Locally executable Stage-8 unit, assurance-unit, contract, golden, and integration suite:

   ```text
   148 passed
   ```

   The isolated overlay emitted 21 unknown-marker warnings because the parent `pyproject.toml` was not mounted in this filesystem; those markers are registered in the accepted repository configuration.

3. Fail-closed Stage-8 acceptance validator:

   ```json
   {"blocked_fixtures": 1, "fixture_files_verified": 9, "projected_fixtures": 7, "schema_files_verified": 3, "schema_version": "gcs008-acceptance-validation-v1", "status": "PASS"}
   ```

4. JSON/YAML/resource checks:

   ```text
   all generated JSON parsed without non-finite constants
   both score-baseline YAML copies matched byte-for-byte
   all fixture-manifest SHA-256 entries matched
   runtime, repository, and packaged public schemas matched
   PASS
   ```

5. Measured non-property Stage-8 coverage gate:

   ```text
   aggregate statement coverage: 92.681388%
   aggregate branch coverage:    85.236220%
   GCS-008 critical-module gate: PASS
   ```

6. Balanced-fixture semantic identities:

   ```text
   input_signature_sha256: 92c3603ce9356f04e2a1611a2e272282703a19dd9d559e3b190c4bc96d042753
   result_sha256:          6537d930643e91629ee793d15aa6f4f86930a36640862aa99b13a201d62b94ea
   ```

The append-only `PLANS.md` update is supplied through `PLANS_GCS008_APPEND.patch`; apply it and delete the helper before running the scope validator or staging. No other gate is claimed as passed locally.

## Generated but not locally executed

- Hypothesis property suite: Hypothesis was unavailable in the isolated runtime.
- Ruff formatting and linting: Ruff was unavailable in the isolated runtime.
- Strict mypy: mypy was unavailable in the isolated runtime.
- Full inherited repository test and coverage suite: the complete parent checkout was not mounted locally.
- Frozen `uv` sync, distribution build, and clean installed-wheel verification.
- Repository-wide validator, first-party secret scanner, and governed evidence validator.
- GitHub Actions execution on the implementation branch.

## Tests requiring PostgreSQL or Docker

GCS-008 adds no database model, table, or migration and therefore adds no Stage-8 migration test. The inherited migration matrix and PostgreSQL integration suite still require the project’s disposable PostgreSQL 18.4 service/Docker environment. They must prove that the unchanged Stage-7 head and inherited persistence paths remain valid.

## Assumptions and decisions

- The accepted Stage-8 roadmap controls the ticket-sized implementation slice over the broader eventual event-engine architecture.
- Stage 7 is consumed as immutable projection provenance and cutoff context. No player-minutes mathematics is copied into Stage 8.
- Explicit home/away Poisson rates are upstream-conditioned request inputs; fitting dynamic attack/defence strengths is outside GCS-008.
- A finite matrix is published only after the omitted tail is within policy. Material overflow is not silently renormalized.
- File artifact persistence is sufficient for this vertical slice; relational run registration belongs to later orchestration.
- Baseline confidence does not establish production promotion without later walk-forward and prospective calibration evidence.

## Unresolved blockers

No unresolved architectural contradiction is known in the reconciled GCS-008 slice.

The remaining validation blockers are environmental rather than hidden implementation placeholders:

- complete clean checkout at the required parent;
- frozen dependency/tool installation;
- Ruff and strict mypy;
- Hypothesis property execution;
- full inherited pytest/coverage suite;
- installed-wheel proof outside the source tree;
- inherited PostgreSQL/migration regression;
- repository, secret, and evidence validators;
- fresh independent review and human stage approval.
