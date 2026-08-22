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
- No remediation-branch GitHub Actions result, remote remediation HEAD, final clean-tree proof, or
  final evidence hashes exist yet.
- Independent review and human acceptance have not occurred. Nothing in this ticket authorizes a
  merge or a modification to PR #16.
