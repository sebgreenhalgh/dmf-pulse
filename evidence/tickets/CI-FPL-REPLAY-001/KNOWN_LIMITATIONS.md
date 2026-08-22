# CI-FPL-REPLAY-001 known limitations

Status: initial evidence; remediation and final verification are incomplete.

- The parent defect is reproduced, but the implementation change and TIME-01 through TIME-18
  regression matrix are not yet complete.
- The exact PostgreSQL 18.4 parent result remains `31 failed, 79 passed, 140 deselected`; no green
  post-remediation PostgreSQL result exists yet.
- Resume at every required lifecycle stage, concurrent replay, ordinary-import non-backdating,
  deterministic quality ordering, and semantic-hash independence remain acceptance gates rather
  than completed claims.
- The migration matrix passed remotely, but it must be rerun locally after remediation and no new
  migration operation may appear.
- The Windows `uv run pytest` launcher shim was blocked by the local execution boundary. The same
  arguments ran via `uv run python -m pytest`; canonical Ubuntu CI must still pass the repository
  command.
- Full coverage, performance, static typing, formatting/lint, build, installed-wheel, repository
  validation, secret scan, and exact FPL/ODD vertical slices have not yet been sealed for the final
  remediation HEAD.
- No remediation-branch GitHub Actions result, remote remediation HEAD, final clean-tree proof, or
  final evidence hashes exist yet.
- `current_manifest.json`, `result.json`, command ledger, coverage report, implementation result,
  and final self-review are intentionally absent until their underlying results exist.
- Independent review and human acceptance have not occurred. Nothing in this ticket authorizes a
  merge or a modification to PR #16.
