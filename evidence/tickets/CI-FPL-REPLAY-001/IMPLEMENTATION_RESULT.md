# CI-FPL-REPLAY-001 implementation result

Engineering checkpoint: `652bae84fba9bdfbf435367d6140270fa8378d57`

Status: `BLOCKED_BY_UNRELATED_CI_TIMEOUT`

Human acceptance: pending; not claimed

Merge: not performed and not authorized

## Outcome

The inherited synthetic replay defect is repaired without changing the cutoff predicate, fixture
dates, provider rights, schema, migrations, Odds ingestion, workflows, or dependencies.

`FplIngestionService.import_pair()` always selects `PROCESSING_TIME_V1`, preserving real
receipt/processing availability for ordinary, manual, and live-shaped ingestion. Only the public
synthetic replay boundary selects `FROZEN_REPLAY_CAPTURED_AT_V1`, after canonical scenario and
fixture-directory validation and only for `synthetic_test_v1`.

The versioned policy is persisted in the existing hash-protected pair context. Resume verifies the
authority and pair-context hash before interpreting the policy. A legacy context without the field
defaults to processing time; unknown policies and frozen policies paired with a non-synthetic
profile fail closed. No migration is required.

## Defensive boundary

- Canonical replay scenarios and resume aliases are explicit allowlists.
- Absolute paths, separators, dot traversal, case variants, and resolved link/junction redirection
  cannot substitute a different fixture directory or frozen timestamp.
- Path-resolution operating-system errors are translated to typed, sanitized ingestion errors.
- Replay with an official profile is rights-blocked before consulting the clock.
- UTC-aware datetimes remain mandatory at replay, ordinary import, operation-time, and persisted
  resume boundaries.

## Direct temporal proof

| Gate | Direct automated proof |
|---|---|
| TIME-01/02/03/07/16/18 | Cross-host-clock happy replay comparison, including bundle semantics, non-empty ordered quality issues, complete processing-event sequences, usable times, and semantic hashes. |
| TIME-04 | Future-host `changed_snapshot` remains frozen at its approved pre-cutoff scenario time. |
| TIME-05/06/15 | `post_cutoff` remains exactly `POST_CUTOFF` and bundle-ineligible under early and future host clocks. |
| TIME-08/09/10/11/12 | Interrupted replay resumes from each incomplete suffix after the historical cutoff without duplicate effects. |
| TIME-13 | Concurrent future-host replay preserves frozen timeline and idempotent semantics. |
| TIME-14 | Ordinary import and ordinary-import resume cannot backdate post-cutoff processing from `captured_at`. |
| TIME-17 | Public ordinary import, replay cutoff, both operation-time modes, and persisted resume context reject naive datetimes. |

The final strengthened temporal slice is `66 passed` with no skip or xfail. The complete
PostgreSQL integration selection changed from the immutable-parent result of
`31 failed, 79 passed, 140 deselected` to `118 passed, 140 deselected` on PostgreSQL 18.4.

## Scope result

The only production file changed is `src/dmf_pulse/ingestion/fpl/service.py`. The immutable-parent
diff is empty for Odds source, LIVE-ODDS ticket/evidence, provider configuration, secret-scan
source, Alembic, workflows, `pyproject.toml`, and `uv.lock`.

Independent adversarial review found no unresolved P0, P1, or material in-scope P2. Branch run
`32598102993` passed the exact PostgreSQL step that failed on PR #16, including
`118 passed, 140 deselected` on PostgreSQL 18.4. GitHub then canceled the job at its configured
35-minute maximum while the next full-coverage command was still running; no test failure was
emitted. The brief forbids workflow changes and requires an unrelated remaining failure to be
reported rather than rerun blindly, so branch-CI success and engineering-ready status are not
claimed.
