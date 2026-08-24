# CI-COVERAGE-SHARD-001 implementation result

Status: `CORRECTED_AFTER_FAIL_CLOSED_TEST_OBSERVATION_PENDING_FINAL_SHA_CI_AND_INDEPENDENT_REVIEW`

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

The heaviest estimated shard completed locally under real branch instrumentation in 606.98 seconds.
The first GitHub architecture run completed every shard job within 13m16s and every pytest command
within 12m45.16s, providing material margin below both the 25-minute target and 35-minute boundary.

## First automatic run and narrow correction

Run `32676529440` on SHA `9805e212daf844ff5335c9e5752db8767375f31b` completed pre-flight
and all eight shard jobs without timeout or cancellation. Shards 0, 1, 3, 4, 6, and 7 passed;
shards 2 and 5 reported 11 failures among all 3,133 exactly-once assignments. Every failure was an
unchanged CLI test comparing ANSI-styled Linux/Typer output directly to the unstyled semantic text.
Combined/post jobs skipped, and the exact-name sentinel failed on the unsuccessful matrix result.

Raw logs proved the commands returned their required exit codes and included the required message.
Following the accepted CI-TEST-002 precedent, only the two affected assertions now apply
`Text.from_ansi(...).plain` before checking the same text. All seven rank and four optimisation
commands, inputs, exit checks, and wording remain unchanged. No workflow color setting, retry, skip,
or other masking was introduced. The correction and exact scope expansion were independently
reviewed with zero P0/P1/material P2/P3 findings.

## Validation and confinement

Focused helper/workflow tests passed 42/42; a broader relevant matrix passed 80/80; focused inherited
optimisation, evaluation CLI, and FPL tests passed 69/69. The two complete corrected modules passed
35/35 with GitHub Actions semantics, including all 11 affected cases. Static formatting, lint,
strict typing, frozen sync, build, the database-free installed GCS wheel check, read-only repository
validation, secret scanning, evidence validation, and repository-manifest validation passed.

The local host had no PostgreSQL service: Docker Desktop's Linux engine was not running and no
`DMF_TEST_DATABASE_URL` was present. The PostgreSQL-dependent ODD wheel verifier correctly refused
to proceed locally. The first automatic run proved PostgreSQL 18.4 pre-flight and every shard
database initialization. Corrected final-SHA Actions must still prove all shards, aggregate/GCS
coverage, and downstream gates.

There are no changes under `src/`, `alembic/`, `config/`, `fixtures/`, `pyproject.toml`, or `uv.lock`.
The only incidental correctness changes are the two allowlisted test assertions. Historical
CI-FPL/CI-TEST/LIVE-ODDS ticket evidence is unchanged. PR #16, independent acceptance, human
acceptance, merge, and production activation are not claimed or performed.
