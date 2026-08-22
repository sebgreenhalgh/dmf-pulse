# CI-FPL-REPLAY-001 acceptance contract

This file defines mandatory engineering gates. It does not assert that they passed, grant human
acceptance, authorize a merge, or authorize any change to PR #16.

## A. Git state and preservation

1. The remediation branch descends directly from immutable parent
   `baed47bce7a158d91afe38351a2c65be60444adf`.
2. The branch is `remediation/CI-FPL-REPLAY-001-deterministic-synthetic-time` and contains no
   LIVE-ODDS commit or cherry-pick.
3. PR #16 remains open and unmodified, with accepted LIVE-ODDS head
   `5e55cf3361a1abff4b2e32dcc30fe42900ea2e16`.
4. The final worktree is clean, local HEAD equals the pushed remediation-branch HEAD, and no force
   push, rebase, main mutation, or merge occurred.
5. The exact diff from the immutable parent remains inside the ticket allowlist. In particular,
   these paths have an empty diff:

   - `src/dmf_pulse/ingestion/odds/**`
   - `tickets/LIVE-ODDS-001/**`
   - `evidence/tickets/LIVE-ODDS-001/**`
   - `config/providers/the_odds_api.json`
   - `src/dmf_pulse/assurance/secret_scan.py`
   - `alembic/**`
   - `.github/workflows/**`
   - `pyproject.toml`
   - `uv.lock`

## B. Root-cause proof

1. The defect is reproduced from the untouched main parent before the implementation change.
2. The recorded evidence distinguishes workflow run `426` / run ID `32588502517` from the local
   reproduction and does not copy the full remote log.
3. The migration matrix is recorded as passing; the next PostgreSQL integration command is
   recorded separately as `31 failed, 79 passed, 140 deselected` on the parent.
4. The same `happy_path` fixture and cutoff are exercised with an injected host clock before and
   after the historical cutoff. Before remediation, the pre-cutoff clock produces a bundle and
   the future clock produces `OBSERVED_NOT_BUNDLE_ELIGIBLE` / `POST_CUTOFF` without a bundle.
5. The frozen `post_cutoff` scenario remains an independent negative control.
6. The causal account traces captured time, host clock, operation/processing timestamps,
   `usable_at`, bundle cutoff eligibility, and the typed exit without diagnosing this as a
   migration or LIVE-ODDS defect.

## C. Authority and semantic boundary

1. `A4-FPL-ingestion`, FPL-004, and the listed DMFP-20 decisions resolve without contradiction.
2. Authorized synthetic replay uses an explicit frozen scenario processing timeline; host wall
   clock is not a replay-semantic input.
3. Ordinary/manual/live ingestion remains tied to actual receipt and processing availability.
   A payload that claims an earlier captured time cannot backdate `usable_at`.
4. `usable_at` is assigned only after every required successful lifecycle stage.
5. Terminal quarantine/rejection never becomes usable.
6. Rights checks remain before transport, raw persistence, canonical promotion, bundle creation,
   backup, training, display, or redistribution. Unknown remains deny.
7. No target-season rule, fixture date, cutoff instant, public contract, dependency, migration,
   workflow, or provider configuration changes.

## D. Temporal regression matrix

- **TIME-01 — pre-cutoff happy path.** With host clock `2026-08-21T17:05:00Z`, fixture capture
  `2026-08-21T17:00:00Z`, and cutoff `2026-08-21T17:30:00Z`, `happy_path` produces a bundle and
  exits zero.
- **TIME-02 — next-day happy path.** The same fixture/cutoff under host clock
  `2026-08-22T18:00:00Z` has the same bundle eligibility and semantic content.
- **TIME-03 — one-year-later happy path.** The same fixture/cutoff one year later retains the same
  deterministic replay semantics.
- **TIME-04 — changed snapshot.** `changed_snapshot`, frozen at `2026-08-21T17:10:00Z`, remains
  valid under a future host clock.
- **TIME-05 — post-cutoff under early host clock.** `post_cutoff`, frozen at
  `2026-08-21T17:31:00Z`, remains ineligible even when the host clock is before cutoff.
- **TIME-06 — post-cutoff under future host clock.** The same scenario remains ineligible under a
  future host clock.
- **TIME-07 — cross-clock semantic equality.** Two identical fixture/cutoff replays under widely
  separated host clocks have semantically identical bundle content apart from the immutable
  retrieval identities/timestamps explicitly excluded by FPL-004.
- **TIME-08 — STORED resume.** Synthetic replay halted after `STORED` resumes after the historical
  cutoff with the original frozen replay timeline and successful result.
- **TIME-09 — PARSED resume.** The equivalent `PARSED` interruption/resume is deterministic.
- **TIME-10 — VALIDATED resume.** The equivalent `VALIDATED` interruption/resume is deterministic.
- **TIME-11 — MAPPED resume.** The equivalent `MAPPED` interruption/resume is deterministic.
- **TIME-12 — PROMOTED resume.** The equivalent `PROMOTED` interruption/resume, where applicable,
  is deterministic and does not duplicate canonical effects.
- **TIME-13 — concurrency.** Concurrent happy replays under a future host clock preserve the same
  replay timeline and expected idempotent canonical semantics.
- **TIME-14 — ordinary import safety.** An ordinary/manual/live operation actually processed
  after cutoff cannot use an earlier captured timestamp to become bundle eligible.
- **TIME-15 — typed post-cutoff.** A future host clock does not turn the expected `POST_CUTOFF`
  negative control into a generic blocker or warning.
- **TIME-16 — deterministic quality and usable time.** Quality-issue ordering, processing-event
  ordering, and `usable_at` remain deterministic for replay.
- **TIME-17 — datetime safety.** UTC enforcement and naive-datetime rejection remain intact for
  replay, resume, and ordinary import.
- **TIME-18 — semantic-hash safety.** Host wall-clock time is absent from replay semantic hashes;
  hash equality/difference follows only the already-approved semantic exclusions and inputs.

Every TIME item must have a direct, non-skipped automated test and recorded result. Bulk-changing
assertions to accept the broken no-bundle output is forbidden.

## E. PostgreSQL and migration acceptance

1. PostgreSQL is exactly 18.4; no SQLite substitute is accepted.
2. The critical command passes with zero failures:

   ```text
   uv run pytest -m "postgres and integration" tests/integration
   ```

3. The inherited migration matrix passes independently:

   ```text
   uv run python scripts/test_migration_matrix.py --baseline-revision 20260803_0005 --target head --report <temporary-path> --offline-sql <temporary-path> --schema-manifest <temporary-path>
   ```

4. No new or rewritten migration operation appears in the remediation diff.
5. The remaining commands from the previously blocked workflow step pass:

   ```text
   uv run alembic upgrade head --sql > <temporary-file>
   uv run dmf data-model doctor --json
   uv run dmf data-model schema-manifest --json
   uv run dmf data-model demo --fixture fixtures/data_model/DAT-003/demo.json --json
   uv run dmf data-model as-of --fixture fixtures/data_model/DAT-003/as_of_queries.json --json
   ```

## F. FPL vertical slice

This exact historical replay succeeds after the real calendar has passed its cutoff:

```text
uv run dmf ingest fpl replay --fixture-set fixtures/fpl/FPL-004 --scenario happy_path --information-cutoff 2026-08-21T17:30:00Z --rights-profile synthetic_test_v1 --output json
```

It must produce a source bundle, exit zero, retain deterministic semantic content, and perform no
provider transport call.

## G. Full regression and package gates

The repository-standard equivalents of all commands below pass and are recorded with exact exit,
duration, and concise result:

```text
uv sync --all-groups --frozen
uv run ruff format --check .
uv run ruff check .
uv run mypy src/dmf_pulse
uv run pytest -m "postgres and integration" tests/integration
uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:<temporary-or-approved-path> -m "not performance"
uv run pytest -m performance tests/performance
uv run dmf specs validate
uv build
uv run python scripts/validate_repository.py
uv run python scripts/scan_secrets.py
```

The FPL synthetic vertical slice, any inherited ODD-005 CI vertical slice, and installed-wheel
verification also pass. No generated output is written into another ticket's historical evidence.

## H. Branch CI and evidence

1. The remediation HEAD is pushed normally and the new branch's `dmf-pulse-ci` run succeeds on
   Ubuntu with PostgreSQL 18.4.
2. A failing CI command is diagnosed from its actual output; CI is not blindly rerun or weakened.
3. Evidence under `evidence/tickets/CI-FPL-REPLAY-001/` truthfully records root cause, commands,
   exact tests, coverage, implementation, limitations, and self-review without large logs or real
   payloads.
4. `evidence/tickets/PRC-013/current_manifest.json` changes only if canonical repository tooling
   requires the mutable active snapshot; no other cross-ticket evidence changes.
5. No unresolved P0/P1 or material in-scope P2 remains after adversarial same-agent review.
6. Final status may be `ENGINEERING_READY_PENDING_INDEPENDENT_REVIEW`; it must not be `ACCEPTED`.
7. Independent review and human acceptance remain separate. This ticket is not merged and PR #16
   remains untouched.

Any failed mandatory item makes the engineering result `BLOCKED` or `FAILED`, never a false
success.
