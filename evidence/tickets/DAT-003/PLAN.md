# DAT-003 implementation plan

- Ticket/stage: `DAT-003`, A3.
- Started: `2026-07-23T13:08:40Z`.
- Required branch: `stage/A3/DAT-003-canonical-foundation`.
- Frozen baseline: `f9b51e965aad1bc94796c17c897f0d99b4c16e1b`.
- Pack: `DMF_PULSE_CODEX_PACK_003_CANONICAL_TEMPORAL_FOUNDATION` v1.0.
- Outcome: close every RUL-002 P1 finding, then deliver the minimum governed
  PostgreSQL 18.4 canonical/bitemporal/provenance vertical slice, installed CLI,
  exact acceptance evidence, and a root-only review ZIP capped at 20 files.

## Frozen preflight

- Git branch, HEAD and clean-tree checks matched the contract before any write.
- All 46 Pack 003 manifest entries matched exact byte counts and SHA-256; all 47
  `20_SHA256SUMS.txt` entries matched.
- The existing 201-test suite ran once without coverage: 200 passed and one failed.
  The sole failure was the prior RUL-002 repository-evidence validator requiring
  the A2 branch after the clean checkout moved to the required A3 branch. DAT-003
  must generalise this validator; no production/rules test failed.
- Docker Engine 29.6.2 and Docker Compose 5.3.1 are available.
- `postgres:18.4-bookworm` is cached as
  `postgres@sha256:1961f96e6029a02c3812d7cb329a3b03a3ac2bb067058dec17b0f5596aca9296`.

## Ordered checkpoints

1. Copy only the frozen DAT ticket/contracts, public schemas and four synthetic
   fixtures required by the milestone; record their exact hashes.
2. Correct R1-R8 with direct regression tests while retaining the byte-identical
   RUL-002 v1.1 reference fixture and Gameweek expected-oracle files.
3. Add exact approved SQLAlchemy/Alembic/Psycopg dependencies, lock/SBOM delta,
   PostgreSQL-only configuration, Compose topology, migration resources and CI.
4. Implement the exact 20-table schema, named constraints/indexes/functions/
   triggers/views, deterministic schema inspection, upgrade/base/re-upgrade and
   offline SQL.
5. Implement strict domain models, explicit-session repositories, controlled
   supersession, as-of queries, immutable observations, rules registry, fixture
   service and the four `dmf data-model` commands.
6. Complete unit/property/real-PostgreSQL/concurrency/immutability/as-of/CLI/wheel
   tests and meet every independent coverage threshold with zero skips.
7. Generalise assurance tooling for DAT-003, create one coherent local commit,
   run the exact 23-command acceptance sequence once with unconditional teardown,
   generate actual-commit evidence, and build/validate the exact 20-file ZIP.

## Exact allowed change surface

- Root/tooling: `pyproject.toml`, `uv.lock`, `.gitignore`, `Makefile`,
  `alembic.ini`, `compose.test.yaml`, `README.md`, `CHANGELOG.md`, `CODE_REVIEW.md`,
  and the existing CI workflows.
- Migration: `alembic/**` plus packaged migration resources under
  `src/dmf_pulse/database/migrations/**` when required for clean-wheel operation.
- Production: `src/dmf_pulse/database/**`, `src/dmf_pulse/data_model/**`, existing
  CLI/config/application wiring, and only the existing rules files required by
  R1-R8.
- Contracts/fixtures: `tickets/DAT-003/**`, `.codex/schemas/**`,
  `fixtures/data_model/DAT-003/**`, and the RUL-002 authored fixtures/goldens
  needed by remediation.
- Tests: targeted rules tests and new DAT unit/property/integration/migration/
  package/security tests.
- Assurance: existing generic evidence, manifest, dependency, wheel, acceptance,
  repository-validation, coverage, secret-scan and review-pack code only where
  DAT-003 requires it; generated output is confined to `evidence/tickets/DAT-003/`
  and `review_pack/DAT-003/`.

Everything else is read-only. No provider HTTP, odds, model, optimiser, API,
scheduler, UI, manager/squad/transfer/chip execution, speculative table, SQLite,
or production secret is permitted.

## Authorised narrow implementation resolutions

- Current temporal exclusions are deferrable so insert-successor-before-close-
  predecessor can execute atomically; repositories explicitly defer the relevant
  named constraint and still rely on PostgreSQL for overlap enforcement.
- Nullable alias language/script scopes use a forbidden reserved sentinel inside
  the exclusion expression so `NULL` cannot bypass preferred-alias non-overlap.
- Supplied fixture omissions are completed with deterministic synthetic defaults
  documented in tests; supplied fixture values are not rewritten or reinterpreted.
- The incomplete 2026/27 ruleset remains non-activatable. Declarative chip/special-
  event capture does not implement effects.
- Generated DAT evidence is ignored after the tracked plan/marker so structured
  results can truthfully name the final committed HEAD while Git remains clean.

## Progress

- [x] `2026-07-23T13:08:40Z` - authority reading, checksum verification, Git,
  baseline-test, Docker/Compose and pinned-image preflight completed.
- [x] `2026-07-23T16:18:00Z` - RUL-002 R1-R8 remediation completed with
  byte-identical protected fixtures and regression/oracle coverage.
- [x] `2026-07-23T17:06:00Z` - PostgreSQL 18.4 toolchain, exact migration,
  20-table schema, schema hash, downgrade and re-upgrade checks completed.
- [x] `2026-07-23T18:12:00Z` - repositories, services, strict models, four CLI
  commands, fixtures, installed-wheel resources and portability boundaries completed.
- [x] `2026-07-23T20:10:00Z` - 279 tests passed with zero skips; branch gates
  passed at 90.21% overall, 98.04% rules and 92.06% data-model/database.
- [ ] Evidence and review ZIP complete.
