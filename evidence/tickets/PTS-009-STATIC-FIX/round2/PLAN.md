# PTS-009-STATIC-FIX-R2 execution plan

Pinned parent: `43270ee54ceff6c4692a6a84118565c16fa6be72`.

1. Validate the ticket, approved A2/A7/A9 authority, clean worktree, and branch.
2. Add focused regressions for activation provenance, Stage-7 binding/minutes,
   BPS ranks, duplicate fixtures, regenerated assurance, Gameweek state, path
   confinement, and real-diff scope detection.
3. Repair the Stage-9-only contracts and deterministic recomputation path.
4. Regenerate the unaccepted Stage-9 schema fixtures only as required, then run
   all stated verification commands and record their actual outputs.

Owner Scope Amendment 1 authorizes exactly
`evidence/tickets/GCS-008/current_manifest.json` for the mutable active
repository snapshot. The required generator invocation is `--ticket GCS-008`;
no PTS manifest or generator/validator change is authorized.

No rules, availability, football-events, dependency, migration, network, or
Stage-10 mutation is permitted.
