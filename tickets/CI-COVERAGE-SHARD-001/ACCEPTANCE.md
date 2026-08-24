# CI-COVERAGE-SHARD-001 acceptance contract

This contract authorizes only the CI execution-architecture change needed to complete the existing
mandatory branch-coverage and downstream acceptance surface within the inherited 35-minute job
boundary. It does not authorize product semantics, test removal, threshold weakening, timeout
increase, LIVE-ODDS modification, PR #16 modification, merge, or human acceptance.

## A. Git and scope

1. The branch starts exactly at `740e70f0ee836a8fab162c56e8345033a06d926b` and retains the
   confirmed direct correctness lineage.
2. CI-GOV commit `6723f121b2b3d2bc477d929e03eb4597eb86df7e` and the disposable
   DIAG-02 observer remain excluded.
3. Only the ticket allowlist changes. `src/`, migrations, config, fixtures, `pyproject.toml`, and
   `uv.lock` remain byte-identical to the parent.
4. LIVE-ODDS head `5e55cf3361a1abff4b2e32dcc30fe42900ea2e16` and PR #16 remain open,
   unmerged, and unchanged.
5. The only permitted incidental correctness changes are ANSI normalization in the two existing
   unsupported-output CLI assertions exposed by automatic run `32676529440`. The same commands,
   exit-code expectations, and semantic message remain mandatory; disabling color in CI is not an
   acceptable substitute.

## B. Exact deterministic partition

1. The planner derives its population from pytest collection with marker expression
   `not performance`; no hand-maintained test allowlist defines eligibility.
2. Normalized nodeids are unique, deterministically ordered, grouped by test file, and assigned by
   deterministic weighted longest-processing-time scheduling with shard-index tie-breaking.
3. Eight shards form a complete disjoint partition. Missing, duplicate, unexpected, malformed, or
   digest-mismatched nodeids fail closed.
4. The canonical plan records commit, marker, population count/digest, shard count, and per-shard
   counts, digests, file counts, weights, and nodeids.
5. The 3,091 eligible tests at the parent remain included; ticket tests are additive.

## C. Coverage transport and combination

1. Every shard uses Ubuntu, Python 3.13, frozen dependencies, PostgreSQL 18.4, initialized Alembic
   schema, `--cov=dmf_pulse`, and `--cov-branch`.
2. Per-shard `--cov-fail-under=0` applies only while transporting partial data. Repository
   `fail_under = 90` remains unchanged.
3. Each shard emits a uniquely named visible coverage-data artifact plus metadata bound to commit,
   shard index, population digest, assigned-nodeid digest, coverage-data bytes, and SHA-256.
4. The combination job independently recollects the exact population, verifies the transmitted
   plan and every expected shard artifact, rejects missing/extra/duplicate/digest-invalid inputs,
   combines coverage.py data, and proves populated branch data.
5. Final combined coverage runs `coverage report --fail-under=90`, writes
   `evidence/tickets/GCS-008/coverage.json`, and passes the unchanged GCS-008 coverage gate.

## D. Preserved CI DAG

1. Pre-flight retains checkout without credentials, Python 3.13, pinned uv, frozen sync,
   conditional GCS scope, format, lint, mypy, PostgreSQL migration/integration, offline SQL,
   doctor, schema manifest, DAT-003 demo, and as-of commands.
2. Post-coverage acceptance receives the combined report and retains performance, FPL/ODD, GCS,
   conditional GCS acceptance, rules, build, installed-wheel, repository, and secret-scan commands.
3. Matrix `fail-fast` is false, but every shard is mandatory.
4. The final job is named exactly `Python 3.13 / Ubuntu`, runs with `if: always()`, depends on all
   mandatory stages, and exits non-zero unless every prerequisite result is `success`.
5. No job timeout exceeds 35 minutes; no retry, `continue-on-error`, allow-failure, marker change,
   test reduction, or threshold reduction exists.

## E. Local and automatic validation

Before publication, helper/workflow tests, real collection partition audit, available shard and
combination checks, focused CI/FPL regressions, diff, Ruff, mypy, build, wheel, read-only repository
validation, secret scan, evidence validation, manifest validation, and scope confinement pass.

If an automatic run exposes a genuine pre-existing test-observation defect, it is classified from
raw logs before correction. A correction may normalize presentation only when it preserves the
tested command, exit code, and semantic text and is recorded in the exact ticket allowlist.

The corrected push-triggered final-SHA run is decisive: pre-flight, every shard, combined coverage,
post-coverage acceptance, and the stable sentinel must succeed without timeout or cancellation.
Shard runtimes and combined statement/branch metrics are reported externally; the branch is not
modified after a successful run merely to record its ID.

## F. Truthful completion

The maximum bounded engineering status is
`CI_ARCHITECTURE_REMEDIATED_PENDING_INDEPENDENT_REVIEW`. Independent review, human acceptance,
merge, production activation, and LIVE-ODDS integration remain separate and unclaimed.
