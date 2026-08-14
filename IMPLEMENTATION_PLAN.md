# GCS-008 implementation plan

## Baseline and authority

- Repository: `sebgreenhalgh/dmf-pulse`
- Required parent: `a5a0b66afd6e9645f971976d723e238824bee6a8`
- Target branch: `stage/A8/GCS-008-goal-clean-sheet-distributions`
- Primary specification: `08_FOOTBALL_EVENT_DISTRIBUTION_ENGINE(6).txt`
- Primary specification SHA-256: `7cb378f26741d28e6b900530102dfdbd2286470c5b8920764792eb70834c18ff`
- Accepted implementation slice: DMFP-19 Stage 8, sections 14.1–14.12
- Frozen dependency: accepted Stage 7 availability/start/minutes implementation and all of its public identities, persistence, packaged replay resources, migrations, CLI contracts, and assurance machinery

The broad DMFP-08 research architecture includes later player allocation and event simulation. GCS-008 implements the accepted Stage-8 vertical slice only: one fixture’s coherent team score and clean-sheet distribution.

## Reconciled Stage-8 contract

### Required inputs

A `score-distribution-request-v1` request contains:

1. Canonical fixture, home-team, and away-team UUIDs.
2. A UTC `as_of` information cutoff and explicit fixture status.
3. A required `stage7-minutes-context-v1` containing identity projections of the accepted home and away `team-minutes-projection-v1` artifacts. Each identity carries the Stage-7 fixture/team/cutoff, model family, dataset hash, model-artifact hash, scenario-set hash, result hash, and fixed sample count.
4. Independent-Poisson prior home and away goal rates. These rates are declared inputs conditioned upstream on the bound Stage-7 context; Stage 8 does not reinterpret player minute PMFs or alter Stage-7 mathematics.
5. Either:
   - an accepted Stage-6 `MarketConsensus`/`MarketNormalisationResult` mapping for `FULL_TIME_1X2`; or
   - a strict tuple of synthetic/generic market constraints for deterministic tests and supported market families.

The Stage-7 identities must match the Stage-8 fixture and teams, share one source cutoff, and be no later than the Stage-8 cutoff. Stage-6 observations and direct constraints must also be usable no later than that cutoff.

### Mathematical model

1. Build independent Poisson marginal PMFs from exact `Decimal` goal rates.
2. Expand each marginal support adaptively until the configured joint omitted-tail tolerance is met, subject to a hard limit and market-line safety margin.
3. Form the retained joint prior and explicitly record the omitted tail before deterministic renormalisation.
4. Translate market events into score-grid design rows for 1X2, totals, team totals, clean sheets, BTTS, and exact scores.
5. Cap aggregate weight within each correlated market family.
6. Solve the convex uncertainty-weighted soft information projection:

   `KL(p || p0) + 1/2 Σ w_k ((A_k p - m_k) / sigma_k)^2`

   using a deterministic Decimal dual Newton method with backtracking.
7. On configured numerical non-convergence, emit a visible degraded prior fallback; otherwise fail closed.

### Canonical outputs

`joint-score-distribution-v1` publishes only exact decimal strings and contains:

- the canonical joint score matrix and adaptive support;
- explicit omitted-tail mass and projection diagnostics;
- home and away goal PMFs;
- home and away goals-conceded PMFs;
- expected home and away goals;
- 1X2 probabilities;
- configured total-goals under/over probabilities;
- home and away clean-sheet probabilities;
- BTTS probabilities;
- deterministic top scorelines;
- per-market target/projected/residual/standardized-residual diagnostics;
- confidence grade and reasons;
- full immutable Stage-7 identity context and derived source hashes;
- Stage-6 source hash when applicable;
- policy, prior, input-signature, and result SHA-256 identities.

All derived probabilities are recomputed from the same rounded public matrix and independently revalidated.

### Precision and identity rules

- Binary floats, booleans at decimal boundaries, NaN, and Infinity are rejected.
- Internal Decimal precision is 60 digits.
- Public probabilities use exactly 12 decimal places and are residual-adjusted to exact simplexes.
- Public expectations and scoring measures use exactly 6 decimal places.
- UTC timestamps must be explicit RFC3339 UTC values; naive and non-UTC values are rejected.
- Canonical JSON uses sorted keys, compact separators, UTF-8, and `allow_nan=False` before SHA-256 hashing.
- Changing market evidence, policy, prior, cutoff, fixture/team identity, or either Stage-7 result identity changes the semantic input and result identities.

### Replay and persistence

The service is pure until explicitly asked to persist. Persistence writes one immutable JSON artifact to a content-addressed path keyed by fixture, cutoff, and input signature. Existing identical content is reused. Existing different content at the same semantic path fails with `ARTIFACT_IDENTITY_CONFLICT`. No mutable `latest` alias is introduced.

### Public commands

- `dmf events score-distribution --fixture <request.json> [--artifact-root <path>] --output json`
- `dmf events explain-market-fit --fixture <request.json> --output json`
- `dmf events evaluate --distribution <artifact.json> --home-goals <n> --away-goals <n> --output json`
- `dmf events validate --distribution <artifact.json> --output json`

All commands are offline and deterministic. TEST/REPLAY paths use packaged policy/resources and synthetic fixtures only.

### Evaluation scaffold

The immutable forecast can be scored after the match with exact-score logarithmic loss, 1X2 Brier score, home/away clean-sheet Brier scores, and home/away goal-count ranked probability scores. Evaluation never mutates the forecast artifact.

### Persistence and migration decision

No database migration is required. GCS-008 adds immutable file artifacts only and must preserve the accepted migration head. The inherited PostgreSQL migration matrix remains an acceptance gate.

### Explicit non-goals

- production bivariate Poisson;
- Dixon–Coles challenger promotion;
- negative-binomial or zero-inflated production selection;
- player scorer or assist allocation;
- shots, saves, penalties, cards, own goals, or defensive events;
- event timing or a full match timeline;
- live provider calls, credentials, network access, or new dependencies.

## File map

### Production

- `src/dmf_pulse/football_events/_decimal.py`
- `src/dmf_pulse/football_events/poisson.py`
- `src/dmf_pulse/football_events/score_grid.py`
- `src/dmf_pulse/football_events/score_prior.py`
- `src/dmf_pulse/football_events/market_constraints.py`
- `src/dmf_pulse/football_events/score_projection.py`
- `src/dmf_pulse/football_events/minutes_context.py`
- `src/dmf_pulse/football_events/score_distribution.py`
- `src/dmf_pulse/football_events/coherence.py`
- `src/dmf_pulse/football_events/evaluation.py`
- `src/dmf_pulse/football_events/service.py`
- `src/dmf_pulse/football_events/__init__.py`
- `src/dmf_pulse/cli/events.py`
- `src/dmf_pulse/cli/app.py`

### Configuration and public resources

- `config/models/score_baseline.yaml`
- `src/dmf_pulse/football_events/resources/score_baseline.yaml`
- `public_contracts/*.schema.json`
- `src/dmf_pulse/football_events/resources/*.schema.json`

### Tests and fixtures

- `tests/unit/football_events/`
- `tests/property/football_events/`
- `tests/contract/football_events/`
- `tests/golden/football_events/`
- `tests/integration/football_events/`
- `fixtures/events/score/GCS-008/`

### Assurance and delivery

- `scripts/check_gcs008_coverage_gates.py`
- `scripts/validate_gcs008_acceptance.py`
- `scripts/validate_gcs008_scope.py`
- `scripts/verify_gcs008_wheel.py`
- `.github/workflows/ci.yml`
- `.github/workflows/windows-smoke.yml`
- `tickets/GCS-008/`
- `evidence/tickets/GCS-008/`
- `PLANS.md` (represented by the delivery-only patch and applied to the accepted parent)
- `IMPLEMENTATION_PLAN.md`, `CHANGED_FILES.txt`, `APPLY_INSTRUCTIONS.md`, `ACCEPTANCE_COMMANDS.ps1`, and `IMPLEMENTATION_RESULT.md`

## Acceptance gates

1. Required-parent and scope validation; Stage-7, migration, dependency-lock, and unrelated paths fail closed.
2. Ruff format and lint.
3. Strict mypy on `src/dmf_pulse`.
4. Unit, property, contract, golden, integration, and adversarial tests.
5. Repository-wide branch coverage plus GCS-008 critical-module statement/branch gates.
6. Synthetic fixture manifest and packaged/repository schema synchronization.
7. Deterministic golden output, Stage-7 identity mutation, market mutation, cutoff leakage, impossible market states, invalid Decimal boundaries, solver fallback, and artifact identity-conflict checks.
8. Full repository tests and inherited disposable-PostgreSQL migration matrix.
9. Wheel build and installed-wheel execution outside the source tree.
10. Repository validation, evidence validation, secret scan, independent review, and human acceptance.
