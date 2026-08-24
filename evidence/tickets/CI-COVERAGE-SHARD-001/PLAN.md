# CI-COVERAGE-SHARD-001 implementation plan

Status: `CORRECTED_AFTER_FAIL_CLOSED_TEST_OBSERVATION_PENDING_FINAL_SHA_CI_AND_INDEPENDENT_REVIEW`

Date: `2026-08-24`

Maximum engineering status:
`CI_ARCHITECTURE_REMEDIATED_PENDING_INDEPENDENT_REVIEW`

## Frozen identity

- Required parent: `740e70f0ee836a8fab162c56e8345033a06d926b`.
- Required branch: `remediation/CI-COVERAGE-SHARD-001-sharded-coverage`.
- Architectural main: `baed47bce7a158d91afe38351a2c65be60444adf`.
- Immutable LIVE-ODDS head: `5e55cf3361a1abff4b2e32dcc30fe42900ea2e16`.
- Excluded timeout-only commit: `6723f121b2b3d2bc477d929e03eb4597eb86df7e`.

## Bounded implementation

- [x] Verify the parent, direct correctness lineage, exclusions, clean baseline, authority, and
  3,091-test parent non-performance collection.
- [x] Add deterministic collection, module grouping, weighted partitioning, canonical manifest,
  per-shard transport metadata, exact artifact verification, and branch-data proof.
- [x] Replace the monolithic workflow with pre-flight, eight PostgreSQL-backed coverage shards,
  combined coverage, post-coverage acceptance, and a fail-closed stable sentinel.
- [x] Contract-test completeness, determinism, transport integrity, aggregate thresholds,
  PostgreSQL preservation, downstream commands, and final status semantics.
- [x] Pass the real implementation-tree partition audit and all locally available focused, static,
  build, repository, security, manifest, and scope checks.
- [x] Classify automatic run `32676529440`: the DAG bounded all shards and failed closed on eleven
  inherited ANSI-sensitive assertions, with no timeout, cancellation, omission, or transport loss.
- [x] Apply and independently review the accepted CI-TEST-002 ANSI-normalization pattern at only
  the two affected assertion sites; preserve every command, exit check, message, and color path.
- [ ] Reseal truthful corrective evidence, publish without force-push, and use the corrected
  automatic final-SHA Actions run as decisive acceptance.

## Publication boundary

The branch will not be changed after a successful final-SHA run merely to record its run ID.
Actions identity, shard runtimes, combined coverage metrics, and downstream state are reported
externally. Independent review, human acceptance, merge, and LIVE-ODDS integration remain separate.
