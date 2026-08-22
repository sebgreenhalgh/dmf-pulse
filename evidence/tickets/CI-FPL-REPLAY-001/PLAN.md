# CI-FPL-REPLAY-001 implementation plan

Status: `IN_PROGRESS`

Updated: `2026-08-22`

Engineering target: `ENGINEERING_READY_PENDING_INDEPENDENT_REVIEW`

## Frozen context

- Immutable remediation parent: `baed47bce7a158d91afe38351a2c65be60444adf`.
- Branch: `remediation/CI-FPL-REPLAY-001-deterministic-synthetic-time`.
- PR #16 was verified open with immutable accepted LIVE-ODDS head
  `5e55cf3361a1abff4b2e32dcc30fe42900ea2e16`.
- GitHub source evidence: `dmf-pulse-ci` run 426, run ID `32588502517`.
- The remote migration-matrix command passed. The following PostgreSQL integration command failed
  on the parent with exactly `31 failed, 79 passed, 140 deselected`.
- Controlled parent reproduction is complete: PRE succeeds; the same happy replay under POST loses
  its bundle through `POST_CUTOFF`; the frozen `post_cutoff` scenario remains ineligible.

## Scope and safety boundary

Only `src/dmf_pulse/ingestion/fpl/service.py`, directly relevant tests, this ticket/evidence,
`PLANS.md`, and the conditionally authorized active PRC-013 repository manifest may change.
No Odds source, workflow, migration, dependency, target-season rule, cutoff, fixture date, or
LIVE-ODDS/PR #16 state may change.

The implementation must make authorized synthetic replay time explicit and deterministic across
replay, resume, and concurrency. Ordinary/manual/live ingestion must continue using actual
availability/processing time and fail closed after cutoff.

## Checkpoints

- [x] Verify immutable parent, remediation branch, PR #16/LIVE-ODDS preservation, and inherited A4
  authority.
- [x] Distinguish the passed migration matrix from the failing PostgreSQL integration command.
- [x] Reproduce the host-clock boundary on the parent with controlled PRE, POST, and `post_cutoff`
  cases.
- [x] Freeze the narrow ticket, acceptance contract, TIME-01 through TIME-18 matrix, and evidence
  plan.
- [ ] Add RED regression coverage for replay across host dates, changed/post-cutoff scenarios,
  resume stages, concurrency, ordinary import safety, UTC handling, quality ordering, and hashes.
- [ ] Implement the smallest explicit replay-time policy in `service.py`, retaining it through the
  existing safe operation context so resume does not require a migration.
- [ ] Run focused tests, then the exact PostgreSQL integration suite and migration matrix on
  PostgreSQL 18.4.
- [ ] Run the remaining blocked workflow vertical slice, FPL CLI replay, static/full/package/wheel/
  repository/security gates, and inspect the exact parent diff.
- [ ] Seal truthful final evidence and manifests only after results and final identities exist;
  commit/push resumably, inspect the remediation branch CI, and stop before independent review.

## Command portability note

On Windows, the `uv run pytest` launcher shim was blocked by the local execution boundary. The
equivalent `uv run python -m pytest` invocation ran with the same pytest arguments and produced the
recorded parent result. Canonical/Ubuntu acceptance still requires the repository command as
written; the substitution is recorded rather than hidden.

## Evidence lifecycle

This is initial evidence only. `current_manifest.json`, `result.json`, coverage, command ledger,
implementation result, final self-review, and any final manifest are intentionally deferred until
their inputs and final Git/CI identities exist.
