# CI-COVERAGE-SHARD-001 implementation result

Status: `IMPLEMENTED_PENDING_AUTOMATIC_FINAL_SHA_CI_AND_INDEPENDENT_REVIEW`

## Architecture

The former sequential job is now a fail-closed DAG:

1. `pre_flight` preserves frozen setup, static analysis, PostgreSQL 18.4 migration/integration,
   offline SQL, doctor, schema, and DAT-003 gates, then emits the canonical shard plan.
2. Eight mandatory `coverage_shards` independently initialize PostgreSQL, run only their assigned
   nodeids with `--cov=dmf_pulse --cov-branch --cov-report= --cov-fail-under=0`, validate the
   branch-aware coverage database, and upload unique visible artifacts.
3. `combined_coverage` freshly recollects the exact population, reconstructs the canonical plan,
   verifies every artifact and binding, combines coverage data, enforces repository coverage at
   90 percent, writes the existing GCS-008 JSON path, proves populated branch counts, and executes
   the unchanged GCS gate.
4. `post_coverage` preserves the inherited performance, FPL/ODD, GCS, rules, build, installed-wheel,
   repository-validation, and secret-scan commands with PostgreSQL 18.4.
5. `quality` retains the exact public name `Python 3.13 / Ubuntu`, runs under `always()`, and fails
   unless every required direct dependency reports `success`.

No job timeout exceeds 35 minutes. Artifact overwrite, retries, failure masking, marker weakening,
and coverage-threshold reduction are absent.

## Deterministic population

The planner uses pytest's collection hooks with the fixed marker expression `not performance`.
It normalizes only the test-file prefix, keeps parameter identifiers byte-stable, rejects malformed
or duplicate nodeids, groups whole modules, and applies repository-local static weights with
deterministic longest-processing-time scheduling and shard-index tie-breaking.

The implementation-checkpoint audit collected 3,133 eligible nodeids: all 3,091 parent nodeids plus
42 additive ticket-test nodeids. The eight-shard union was exact and disjoint with no empty shard.
The stable eligible population digest is
`e6bce2db465dd0ea34560336d3127d8fd2ce180c6250db3067cdaba4fa89199f`.

The heaviest estimated shard completed locally under real branch instrumentation in 606.98 seconds,
providing material margin below both the 25-minute target and 35-minute hard boundary. GitHub-hosted
Ubuntu runtimes for all eight shards remain the decisive acceptance measurement.

## Validation and confinement

Focused helper/workflow tests passed 42/42; a broader relevant matrix passed 80/80; focused inherited
optimisation, evaluation CLI, and FPL tests passed 69/69. Static formatting, lint, strict typing,
frozen sync, build, the database-free installed GCS wheel check, read-only repository validation,
secret scanning, evidence validation, and repository-manifest validation passed.

The local host had no PostgreSQL service: Docker Desktop's Linux engine was not running and no
`DMF_TEST_DATABASE_URL` was present. The PostgreSQL-dependent ODD wheel verifier correctly refused
to proceed. The workflow preserves its exact command and supplies PostgreSQL 18.4; final-SHA Actions
must prove it along with all shards, aggregate/GCS coverage, and downstream gates.

There are no changes under `src/`, `alembic/`, `config/`, `fixtures/`, `pyproject.toml`, or `uv.lock`.
Historical CI-FPL/CI-TEST/LIVE-ODDS ticket evidence is unchanged. PR #16, independent review, human
acceptance, merge, and production activation are not claimed or performed.
