# CI-COVERAGE-SHARD-001 root cause

Classification: `KNOWN_EXTERNAL_CI_ARCHITECTURE_BLOCKER`

Automatic run `32667375839` executed the independently confirmed correctness-stack head
`740e70f0ee836a8fab162c56e8345033a06d926b`. Checkout, frozen setup, formatting, lint, strict
typing, and the PostgreSQL 18.4 migration/integration step all succeeded. The sole job then reached
the monolithic repository branch-coverage command and exceeded its inherited 35-minute job limit.

The retained raw coverage-step log contains no pytest failure marker, failure summary, collection
error, traceback, or failing-test progress before cancellation. It reached only 1 percent after
executing known optimisation-heavy modules. The job conclusion and annotations identify the
35-minute maximum and operation cancellation. A prior timeout-only experiment at
`6723f121b2b3d2bc477d929e03eb4597eb86df7e` also failed to establish a reliable completion
boundary and is excluded from this branch.

The defect is therefore structural: one job performs setup, static analysis, PostgreSQL
acceptance, the entire non-performance suite under branch instrumentation, every downstream
vertical slice, build, wheel verification, repository validation, and secret scanning in series.
Increasing or removing the timeout would not create a bounded, reliable architecture.

The remediation derives the exact `not performance` population from pytest, assigns whole test
files by deterministic weighted longest-processing-time scheduling, executes eight mandatory
isolated coverage shards, verifies every artifact and the complete partition, combines branch data,
applies the unchanged 90 percent repository floor and GCS-008 gates, then runs every inherited
downstream command. An exact-name sentinel fails unless every mandatory DAG stage succeeded.
