# Stage 9 verification and handoff

The candidate overlay has already been reconciled on
`stage/A9/PTS-009-fpl-points-simulation` at accepted parent
`9d7c360ab6a4cc7bfc6d6f41e44be6b47512b272`. Do not reapply the archive over this
tree.

## Verify the integrated tree

From `C:\Users\sebgr\Documents\dmf-pulse`:

```powershell
git branch --show-current
git merge-base HEAD 9d7c360ab6a4cc7bfc6d6f41e44be6b47512b272
git status --short
pwsh -File .\ACCEPTANCE_COMMANDS.ps1
```

`ACCEPTANCE_COMMANDS.ps1` runs the frozen sync, generated-resource, scope, static,
focused, compatibility, database, repository coverage, offline CLI, artifact, wheel,
repository, secret, and whitespace gates in dependency order. It uses a disposable
loopback PostgreSQL database and removes its volume in `finally`.

The Stage 9 performance smoke is intentionally separate from coverage instrumentation.
The repository coverage run excludes `tests/performance`; all functional tests remain
in that regression. The current repository manifest is refreshed immediately before
its integration test and again after the coverage JSON is written.

## Commit and publish contract

After all gates pass, verify the declared and actual changed paths match, then create
exactly one commit:

```powershell
git add -- <reviewed Stage-9 paths>
git commit -m "feat(fpl-points): implement PTS-009 simulation"
git push -u origin stage/A9/PTS-009-fpl-points-simulation
```

Do not amend with a second implementation commit, force-push, merge, self-accept, or
open a PR without a separate request.

## Review boundary

The implementation evidence proves integration gates, not independent acceptance.
Production remains blocked while `RULESET_READINESS.md` reports the target ruleset as
inactive and unapproved.
