# OPT-011 test and validation results

## Passing engineering gates

| Gate | Result |
|---|---|
| Frozen dependency sync | PASS, 40 packages audited |
| Ruff format | PASS, 453 files already formatted |
| Ruff lint | PASS, no findings |
| Strict mypy | PASS, 165 source files |
| Final Stage-11 unit/property/oracle/golden/contract suite | PASS, 268 tests in 59.22 s |
| Relevant Stage-9/10/rules regression suite | PASS, 430 tests in 468.52 s |
| PostgreSQL/migration slice | PASS, 205 tests in 308.33 s |
| Stage-11 branch coverage | PASS, 2,193/2,404 = 91.222962% |
| Stage-11 plus mixed CLI branch coverage | PASS, 2,285/2,521 = 90.638635% |
| Build | PASS, sdist and wheel for `dmf-pulse==0.2.0` |
| General clean installed-wheel verification | PASS outside repository |
| Installed-wheel Stage-11 optimise/advance | PASS; both exit 0, result advances to GW2 |
| Source CLI optimise/advance acceptance | PASS with immutable artifacts |
| Artifact/config/fixture assurance | PASS, exact 20-case set |
| Exact-parent scope assurance | PASS, 92 changed files with production/tests/fixtures present |
| Repository validation | PASS, zero errors |
| Secret scan | PASS, zero findings |
| Compileall | PASS for Stage-11 source and assurance scripts |
| `git diff --check` | PASS |
| Benchmark smoke | PASS, three representative cases, three runs each |

The independent oracle is test-owned. Source-assurance tests prohibit production solver and
Stage-10 adapter calls from the oracle implementation. Tiny deterministic and scenario-tree
cases reconcile policy value, transfers, hits, bank/free-transfer transitions, and terminal
value independently.

## Repository-wide run

The documented digest-pinned disposable PostgreSQL 18.4 service was provisioned and migrated.
The final repository-wide run passed **2,142 tests with zero failures and zero skips in
1,346.40 seconds**. The database/migration slice also passed independently: 205 tests in
308.33 seconds.

The complete repository-wide branch-coverage run was attempted with the same database but hit
the 30-minute command cap without emitting a test failure. It is recorded as `RESOURCE_LIMIT`,
not PASS. Relevant Stage-11 branch coverage completed independently and exceeds the required 90%
threshold; no coverage exclusions or deleted meaningful branches were used.

No timed-out, deselected, or pre-finalization result is counted as a final pass.
