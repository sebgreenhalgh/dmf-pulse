# CI-FPL-REPLAY-001 root cause

Status: `REPRODUCED_ON_IMMUTABLE_MAIN_PARENT`

Evidence phase: initial, before remediation

## Classification

`INHERITED_MAIN_DEFECT`

The failure reproduces directly on immutable `main` parent
`baed47bce7a158d91afe38351a2c65be60444adf`, without incorporating the accepted LIVE-ODDS head.
This establishes that the blocked integration exposed an inherited FPL defect rather than creating
one in LIVE-ODDS. The final scope review must still retain the exact empty Odds/LIVE-ODDS diff.

## CI evidence

- Blocked PR: #16, verified open.
- Accepted PR head: `5e55cf3361a1abff4b2e32dcc30fe42900ea2e16`.
- Workflow: `dmf-pulse-ci`, run 426, run ID `32588502517`.
- The migration-matrix command in the composite workflow step passed remotely.
- The following PostgreSQL integration command failed on the parent with exactly
  `31 failed, 79 passed, 140 deselected`.

The workflow-step title therefore does not make this a migration failure.

## Controlled parent reproduction

The inherited synthetic fixture timeline is fixed:

- `happy_path` captured at `2026-08-21T17:00:00Z`;
- `changed_snapshot` captured at `2026-08-21T17:10:00Z`;
- `post_cutoff` captured at `2026-08-21T17:31:00Z`;
- information cutoff `2026-08-21T17:30:00Z`.

| Case | Injected host clock | Observed parent behavior |
|---|---|---|
| PRE | `2026-08-21T17:05:00Z` | Happy replay succeeds and produces its bundle. |
| POST | `2026-08-22T18:00:00Z` | The same happy replay loses its bundle through the typed `POST_CUTOFF` path. |
| `post_cutoff` | Controlled host clock | The frozen after-cutoff scenario remains ineligible, as required. |

On Windows, the `uv run pytest` launcher shim was blocked by the local execution boundary. The
same pytest arguments ran through `uv run python -m pytest`; the substitution and result are
retained explicitly.

## Causal mechanism

At the immutable parent, `FplIngestionService` defaults to the real UTC clock. Its operation-time
calculation takes the later of the fixture's captured time and the current host time. Replay assigns
the frozen historical capture time and then enters the ordinary import lifecycle. Consequently:

1. before the historical cutoff, operation and lifecycle timestamps remain eligible;
2. after the real calendar passes the cutoff, the host clock becomes operation time for the exact
   same frozen fixture;
3. required-stage completion and `usable_at` then occur after the fixed historical cutoff;
4. bundle freezing raises typed `POST_CUTOFF`;
5. the service preserves the observations but returns no source bundle as
   `OBSERVED_NOT_BUNDLE_ELIGIBLE` with nonzero exit.

Resume has the same defect boundary because it reconstructs captured time from the stored context
but recomputes operation time against the current host clock. A replay interrupted before the
historical cutoff can therefore change result merely because it resumes later.

## Required correction

Authorized synthetic replay must use an explicit frozen processing timeline derived from the
scenario and retain that policy through resume and concurrency. It must not use the later host
calendar date as a semantic input. Ordinary/manual/live import must still use actual processing
availability; globally replacing operation time with `captured_at` would backdate real data and is
forbidden.

The existing cutoff predicate and typed `POST_CUTOFF` handling remain correct. The defect is which
clock feeds synthetic replay lifecycle time, not the database schema, migration history, rights
gate, cutoff instant, fixture date, or bundle eligibility rule.
