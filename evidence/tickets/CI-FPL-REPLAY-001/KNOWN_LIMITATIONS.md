# CI-FPL-REPLAY-001 known limitations

Status: local implementation verified; remote CI and independent review are pending.

- The exact PostgreSQL 18.4 parent result was `31 failed, 79 passed, 140 deselected`; the same
  post-remediation slice is green at `118 passed, 140 deselected`.
- The Windows `uv run pytest` launcher shim was blocked by the local execution boundary. The same
  arguments are run locally through `uv run python -m pytest`; canonical Ubuntu CI must still pass
  the literal repository command.
- The first two repository-wide coverage attempts were terminated only by local wrapper ceilings
  at 15 and 40 minutes. The completed Windows coverage run measured 93.59% statements and 86.35%
  branches; its only reproducible failure was the deliberately stale current repository manifest,
  which is regenerated after all non-evidence edits and followed by a clean full-suite rerun.
- The canonical review-pack builder does not support remediation ticket identifiers. Extending it
  would require unauthorized assurance-code scope, so this ticket supplies hash-sealed evidence
  without claiming a canonical review pack.
- Branch run `32598102993` proved the repaired PostgreSQL 18.4 step green at
  `118 passed, 140 deselected` in 186.59 seconds, then GitHub canceled the job at its hard
  35-minute limit while full coverage was still running. The canceled step emitted no test
  failure. Raising or restructuring that limit requires a forbidden workflow change and is an
  unrelated follow-up, so the branch cannot truthfully be called engineering-ready in this ticket.
- The pushed remote checkpoint is `652bae84fba9bdfbf435367d6140270fa8378d57`; the blocked final
  evidence is sealed in a later local-only resumable commit to avoid blindly triggering the same
  unchanged timeout.
- Independent review and human acceptance have not occurred. Nothing in this ticket authorizes a
  merge or a modification to PR #16.
