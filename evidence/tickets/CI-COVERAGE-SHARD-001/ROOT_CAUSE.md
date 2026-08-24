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

## First architecture-run discovery

Automatic run `32676529440` on implementation SHA
`9805e212daf844ff5335c9e5752db8767375f31b` validated the bounded execution architecture. Pre-flight
passed, all eight PostgreSQL-backed shards ran, six passed, and the maximum shard job runtime was
13m16s. Two shards failed only after correctly executing their assigned tests: seven rank and four
optimisation CLI assertions compared raw ANSI-styled Typer output to an unstyled substring. The
semantic message and required exit codes were present; ANSI control sequences split the literal.

This is a separate `TEST_OBSERVATION_DEFECT`, not an architecture, product, database, timeout, or
coverage-transport defect. The parent monolith had never reached these tests on Linux. The accepted
CI-TEST-002 correction establishes the narrow remedy: normalize ANSI only at assertion time. The
two sibling assertions now use that exact pattern; disabling color in CI was rejected as masking.
