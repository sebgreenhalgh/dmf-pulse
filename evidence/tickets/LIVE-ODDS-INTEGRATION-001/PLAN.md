# LIVE-ODDS-INTEGRATION-001 implementation plan

Status: `INTEGRATION_CANDIDATE_PENDING_FINAL_SHA_CI_AND_INDEPENDENT_REVIEW`

Date: `2026-08-24`

## Frozen identity

- First parent: `fceca02d21ec7031e36518c46724c6a6d3d6c72e`.
- Accepted second parent: `5e55cf3361a1abff4b2e32dcc30fe42900ea2e16`.
- Common base: `baed47bce7a158d91afe38351a2c65be60444adf`.
- Branch: `integration/post-ci/LIVE-ODDS-001-on-repaired-main`.
- Reconciliation verdict: `LIVE_ODDS_RECONCILIABLE_WITH_REPAIRED_MAIN`.

## Checkpoints

- [x] Fetch and verify exact origin refs, main push CI, immutable LIVE-ODDS source, PR #16, merge
  base, target-branch absence, and clean startup.
- [x] Create the branch from repaired main and start an explicit no-commit, no-fast-forward merge of
  the accepted source.
- [x] Confirm exactly two governance conflicts and zero executable conflicts.
- [x] Preserve the exact repaired-main and LIVE-ODDS programme histories in the required order.
- [x] Prove pre-commit identity for all 20 accepted and 16 repaired-main protected blobs.
- [x] Pass focused LIVE-ODDS and repaired-main regression matrices on PostgreSQL 18.4.
- [x] Pass frozen sync, format, lint, strict typing, build, and installed-wheel validation.
- [x] Seal final integration evidence, regenerate only the active PRC manifest, and pass repository,
  security, scope, and pre-commit index audits.
- [ ] Create exactly one two-parent merge commit, repeat identity audits, and generate the final
  eight-shard population plan.
- [ ] Push only the integration branch and require the automatic final-SHA run to pass completely.
- [ ] Stop for independent integration review without creating a PR or claiming human acceptance.

## Publication boundary

The final branch is not changed after successful final-SHA CI merely to record its run identity.
The run, runtimes, shard population, and final engineering status are reported externally.
