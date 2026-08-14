# GCS-008 implementation result

## Status

The complete Stage-8 implementation and the six GCS-008 R1 independent-review remediations are present on `stage/A8/GCS-008-goal-clean-sheet-distributions`. Stage 8 is based on required parent `a5a0b66afd6e9645f971976d723e238824bee6a8`; R1 started from exact implementation commit `668662a1c9a3f3a92d1c0305e6dfbf6b1d32a07a`.

The complete 3,513-line `08_FOOTBALL_EVENT_DISTRIBUTION_ENGINE(6).txt` specification (SHA-256 `7cb378f26741d28e6b900530102dfdbd2286470c5b8920764792eb70834c18ff`) and accepted repository contracts were reconciled before implementation. `main` and PR #2 remain unmerged.

## Implemented

- Exact-Decimal independent-Poisson home/away score prior.
- Adaptive score support with explicit omitted-tail diagnostics and fail-closed maximum support.
- Typed score-grid events for 1X2, totals, team totals, clean sheets, BTTS, and exact scores.
- Strict accepted Stage-6 `MarketConsensus`/`MarketNormalisationResult` input, including fixture, cutoff, outer and nested `as_of`, bounds, disagreement, freshness, operator lineage, and semantic-hash validation.
- Read-only Stage-7 home/away projection identity contract with fixture/team/cutoff validation and replay-hash binding; no Stage-7 formula or public contract was altered.
- Market-family weight caps and deterministic uncertainty-weighted soft KL projection.
- Visible typed prior fallback only when the immutable policy permits it.
- Canonical `joint-score-distribution-v1` containing the matrix, goal PMFs, goals-conceded PMFs, expected goals, 1X2, totals, BTTS, clean sheets, scorelines, residuals, diagnostics, confidence, and complete lineage.
- Independent coherence validation and canonical SHA-256 identities.
- Atomic content-addressed JSON persistence with identity-conflict rejection.
- Offline Typer commands for projection, market-fit explanation, validation, and realized-score evaluation.
- Canonical fixed-precision public Decimal schemas in repository contracts and packaged resources.
- Proper-score evaluation for exact score, team goals, 1X2, clean sheets, and BTTS.
- Synthetic TEST/REPLAY fixtures, checksum manifest, reviewed golden output, scope/coverage/acceptance validators, and installed-wheel verification.
- R1 matrix-derived validation of every supported market residual and aggregate market-fit diagnostic.
- R1 tracked baseline policy, non-empty coverage denominators, and explicit Stage-8 production allowlist.
- Unit, property, contract, golden, integration, CLI, and adversarial tests.
- Linux CI and Windows smoke workflows.

## Deliberately unchanged

- Accepted Stage-7 algorithms, public models, persistence, packaged replay resources, migration, CLI, and assurance machinery.
- Accepted Stage-6 normalization mathematics and persistence.
- Joint-score projection mathematics and published probability matrix.
- Alembic head `20260807_0006`.
- `pyproject.toml`, `uv.lock`, `pylock.toml`, and the dependency set.
- `main`.

## Actually executed in this implementation environment

The following results were measured under Python 3.13.9 in the complete repository after all R1 product, test, schema, and resource changes:

1. Frozen sync and static assurance: `uv sync --all-groups --frozen`, `git diff --check`, Ruff format/lint, and strict mypy all passed; Ruff checked 340 files and mypy checked 124 source files.
2. Combined GCS-008 unit, property, contract, golden, integration, CLI, and assurance selection: 209 passed (187 unit/assurance, 5 property, 17 contract/golden/integration).
3. Final complete repository regression: 1,614 passed in 678.60 seconds. Coverage was 14,713/15,744 statements (93.451474%), 4,373/4,914 branches (88.990639%), and 92.390357% combined.
4. Critical GCS-008 coverage gate: 93.066348% statements and 85.818182% branches across 14 required files, with positive, count-consistent denominators for every required module.
5. Fail-closed GCS-008 acceptance validation: 79 parent-to-tree files, 23 tracked acceptance inputs, 9 fixture files, 3 synchronized public schemas, 7 projected fixtures, and 1 correctly blocked fixture; status PASS.
6. All four public CLIs passed against a fresh content-addressed artifact root: `score-distribution`, `explain-market-fit`, matrix-recomputing `validate`, and `evaluate`.
7. PostgreSQL 18.4 migration matrix passed through Alembic head `20260807_0006`; canonical schema SHA-256 `7466ab96b6ffa19236cfa197e480c7bef86d57c4bb8f486d55fcfdec39bf57cc`. The PostgreSQL integration selection passed 110 tests with 110 deselected.
8. `uv build` and isolated installed-wheel verification passed. All 158 RECORD members and the four GCS-008 packaged resources were verified. Wheel SHA-256: `8203c9cc0db9a945804890a62162c5f4567f7785ad0c18db9a44034c9a2dfd66`.
9. Repository validation and the first-party secret scan passed with zero findings.
10. Balanced-fixture identities: input signature `92c3603ce9356f04e2a1611a2e272282703a19dd9d559e3b190c4bc96d042753`; result identity `31d41317c0cf06002edd8e8fb47c4702706661f2227304182e3c4b8995e06b7e`. The input signature and probability matrix are unchanged; the result identity changed because residual records now publish the exact-score coordinates required for independent reconstruction.

## Independently reproduced R1 findings

1. Stage-6 envelope tests accept outer/nested timestamps at the cutoff and reject post-cutoff, malformed, naive, and inconsistent outer envelopes without weakening nested checks.
2. Validation mutation tests cover all 14 supported score events plus projected, residual, standardized residual, RMSE, and maximum-residual fields; the reviewer-style recomputed-self-hash attack is rejected as `ARTIFACT_INVALID`.
3. Public schemas accept only canonical fixed-precision Decimal strings; JSON numbers and trailing-zero aliases are rejected at runtime and cannot acquire a second semantic identity. Repository and packaged schema copies are byte-synchronized.
4. `config/models/score_baseline.yaml` is tracked through an exact `.gitignore` exception, byte-equal to its packaged resource, and included in the validator's Git-index inventory.
5. Coverage mutation tests reject all-zero, zero-statement, zero-branch, missing, malformed, duplicate, impossible, and percentage-conflicting records while accepting genuine current coverage.
6. The scope validator uses an explicit Stage-8 production allowlist and rejects later-stage scorer, assist, card, save, penalty, timing, simulation, FPL-points, optimizer, and optimisation modules.

## Tests requiring PostgreSQL or Docker

GCS-008 adds no database model, table, or migration. The inherited disposable-PostgreSQL migration matrix and integration suite were nevertheless executed and passed as recorded above, proving the unchanged Stage-7 Alembic head and inherited persistence paths remain valid.

## Assumptions and decisions

- The accepted Stage-8 roadmap controls this ticket-sized implementation slice over the broader eventual event-engine architecture.
- Stage 7 is consumed as immutable projection provenance and cutoff context. No player-minutes mathematics is copied into Stage 8.
- Explicit home/away Poisson rates are upstream-conditioned request inputs; fitting dynamic attack/defence strengths is outside GCS-008.
- A finite matrix is published only after the omitted tail is within policy. Material overflow is not silently renormalized.
- File artifact persistence is sufficient for this vertical slice; relational run registration belongs to later orchestration.
- Baseline confidence does not establish production promotion without later walk-forward and prospective calibration evidence.

## Unresolved blockers

No local implementation or validation blocker remains. GitHub Actions, fresh independent review, and human stage approval remain external and are not self-asserted here.
