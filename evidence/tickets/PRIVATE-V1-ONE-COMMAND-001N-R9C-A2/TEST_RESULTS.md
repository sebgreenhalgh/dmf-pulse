# R9C-A2 offline test results

The A2 implementation is validated only with synthetic/provider-shaped fixtures before publication.
No live result belongs in repository evidence.

| Surface | Result |
| --- | --- |
| A2 focused, including acquire-once canonical four-world solve | PASS - 63 |
| A1.01/A1.02/A1.03 and R9A/R9B regression | PASS - 120 |
| Selected private-v1/one-command/provider regression | PASS - 234 |
| Stage 9/10/11 unit, contract and golden regression | PASS - 622 |
| Complete unit ingestion | PASS - 1,148 |
| New A2 module branch-aware coverage | 92% |
| Ruff format/check | PASS |
| Strict mypy | PASS - 294 source files |

Six PostgreSQL security tests require `DMF_TEST_DATABASE_URL` and stopped at fixture setup when that
environment variable was unavailable. The first-party repository secret scan and remaining
repository/build gates are run separately and recorded in the command ledger.

After the first independent review, focused remediation tests additionally prove exact full-metadata
authority rejection before provider construction, cutoff enforcement before provider phases and
every FPL attempt/retry, the three previously omitted control hashes, measured zero provider calls,
global socket/provider-construction denial, and closed safe-summary failure.

The final re-review remediation additionally proves the operator-approval lower bound, exact FPL
terms/unresolved-rights/deletion metadata rejection before all factories, and a default-off guard
before each reconstructed score-prior resource transport. The complete OpenFootball plus A2 suite
passes 162 tests after those changes.

The frozen final branch run passes all 33 A2 tests in 602.31 seconds. The new A2 module reports
92% branch-aware coverage; the complete 129-test OpenFootball suite raises the affected score
service to 95%, for 93% across those two changed modules.
