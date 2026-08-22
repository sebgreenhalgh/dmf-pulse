# CI-GOV-001 implementation plan

Status: `IN_PROGRESS`

Updated: `2026-08-22`

Engineering target: `ENGINEERING_READY_PENDING_INDEPENDENT_GOVERNANCE_REVIEW`

## Frozen context

- Architectural main parent: `baed47bce7a158d91afe38351a2c65be60444adf`.
- Stacked remote technical parent: `652bae84fba9bdfbf435367d6140270fa8378d57`.
- Protected local-only CI-FPL evidence commit `244feb0709294c3a544e399c7890177120dd1020`
  is not an ancestor dependency and its worktree remains untouched.
- PR #16 is open at immutable LIVE-ODDS head
  `5e55cf3361a1abff4b2e32dcc30fe42900ea2e16`.

## Bounded implementation

- Change only the quality job's timeout from 35 to the owner-authorized 60 minutes.
- Preserve the entire workflow acceptance surface and failure semantics.
- Prove zero product, test, config, migration, and dependency delta.
- Run bounded local governance validation, then let the push-triggered workflow provide the
  decisive full execution proof.
- Stop at 60 minutes or any newly exposed required-gate failure.

## Checkpoints

- [x] Verify remote identities, worktree isolation, PR #16, and pre-change run evidence.
- [x] Inspect every workflow command and confirm only execution budget is defective.
- [x] Apply the exact 35-to-60-minute change and create the ticket/evidence boundary.
- [x] Run local scope, YAML, static, repository, and security gates.
- [ ] Commit/push normally and wait for the complete 60-minute Actions result.
- [ ] Record timings, seal manifests/evidence, push final evidence, and stop before review/merge.
