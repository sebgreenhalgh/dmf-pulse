# CI-FPL-REPLAY-001 final self-review

Status: `BLOCKED_BY_UNRELATED_CI_TIMEOUT`

## Correctness and authority

- The implementation separates deterministic, authorized synthetic replay time from real
  processing time. It does not globally backdate operation time.
- The strict `usable_at <= information_cutoff` publication boundary remains unchanged.
- Ordinary import and ordinary resume retain host processing time and fail closed after cutoff.
- Frozen replay requires the exact synthetic rights profile; rights checks remain before fixture
  approval/persistence and publication.
- The explicit scenario-to-time map is bound to the resolved approved fixture directory, closing
  traversal, case-folding, absolute-path, symlink, and junction substitution paths.
- Resume authenticates the existing pair context before policy use; legacy absence defaults to the
  safer processing-time policy and unknown/tampered values reject.

## Determinism and lifecycle

- TIME-01 through TIME-18 have direct non-skipped automated coverage.
- TIME-16 compares non-empty quality ordering, full processing-event ordering, and usable times
  across host clocks rather than relying on a vacuous empty projection.
- TIME-17 directly exercises naive datetime rejection at public ordinary import, replay cutoff,
  operation-time, and persisted resume boundaries.
- Concurrent replay, interrupted suffix resume, semantic hashes, and immutable bundle semantics
  remain deterministic without wall-clock sleeps.

## Scope and security

- Production diff: `src/dmf_pulse/ingestion/fpl/service.py` only.
- No Odds source, LIVE-ODDS ticket/evidence, provider configuration, secret scanner, Alembic,
  workflow, dependency, target-season rule, fixture-date, or cutoff change.
- No provider transport or real credential access occurred. Installed-wheel validation recorded
  zero network requests, and first-party secret scanning found zero findings.
- The only cross-ticket evidence mutation is the explicitly authorized mutable
  `evidence/tickets/PRC-013/current_manifest.json` refresh required by repository validation.

## Adversarial findings

- P0: none.
- P1: none.
- Material in-scope P2: none.
- Closed findings included unsafe profile-only policy selection, scenario traversal/case/link
  substitution, arbitrary resume aliases, untyped path-resolution errors, a vacuous TIME-16
  comparison, and incomplete direct TIME-17 boundary coverage.

## Honest limitations

- Windows App Control blocks the local `uv run pytest` shim; equivalent local commands use
  `uv run python -m pytest`. Ubuntu CI must pass the literal commands.
- The canonical review-pack builder rejects remediation ticket IDs. Assurance production scope was
  not expanded to add support; the evidence directory is instead sealed by its canonical ticket
  evidence manifest.
- The branch's repaired PostgreSQL step is green, but the overall workflow was canceled at the
  pre-existing 35-minute job maximum during full coverage. The step emitted no test failure.
  Workflow expansion is explicitly excluded, and the brief says to report an unrelated remaining
  failure instead of rerunning blindly. Engineering-ready, independent-review, and human
  acceptance status therefore remain unclaimed. No merge or PR #16 mutation is authorized.
