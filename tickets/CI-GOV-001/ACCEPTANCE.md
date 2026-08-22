# CI-GOV-001 acceptance contract

This contract authorizes exactly one workflow semantic change: increase the `quality` job's hard
runtime budget from 35 to 60 minutes. It does not authorize human acceptance or any merge.

## A. Git and stacked review boundary

1. The branch `governance/CI-GOV-001-ci-runtime-budget` starts exactly at remote technical head
   `652bae84fba9bdfbf435367d6140270fa8378d57`, not local-only commit `244feb...`.
2. Architectural `main` remains `baed47bce7a158d91afe38351a2c65be60444adf`.
3. The final governance layer is reviewed independently as `652bae84..<final-head>`.
4. No rebase, force push, main mutation, tag, merge, or PR creation occurs.

## B. Pre-change proof

1. Run `32598102993` is inspected from its actual metadata and log.
2. PostgreSQL 18.4 integration passed `118 passed, 140 deselected` before termination.
3. Coverage began, ran until the whole job exhausted its 35-minute budget, and emitted no real
   test failure before cancellation.
4. Performance, vertical slices, rules, build, wheel, repository validation, and secret scan were
   skipped only because the job had already been canceled.

## C. Exact workflow change

1. `.github/workflows/ci.yml` changes only `timeout-minutes: 35` to `timeout-minutes: 60`.
2. PostgreSQL image/digest, environment, commands, ordering, conditions, selection, coverage gates,
   failure semantics, and permissions remain byte-identical.
3. No retry, parallelization, split job, cache-semantic change, `continue-on-error`, skip, xfail,
   marker change, or threshold reduction is introduced.

## D. Zero product delta

The diff from `652bae84...` is empty for `src/`, `tests/`, `config/`, `alembic/`, `pyproject.toml`,
and `uv.lock`. In particular, the FPL service is byte-identical to the technical parent.

## E. Local validation

The following pass before push:

```text
git diff --check
YAML parse and exact workflow semantic comparison
uv run ruff format --check .
uv run ruff check .
uv run mypy src/dmf_pulse
uv run python scripts/validate_repository.py
uv run python scripts/scan_secrets.py
```

Repository validation may use the identical read-only validator function locally if the CLI main
would write an unauthorized historical-ticket report. GitHub must execute the literal unchanged
CLI step.

## F. Full GitHub Actions result

1. Push-triggered `dmf-pulse-ci` uses exactly `timeout-minutes: 60`.
2. The single Ubuntu job succeeds within 60 minutes.
3. Every unconditional required step receives `SUCCESS`: PostgreSQL, coverage, performance,
   FPL/Odds, GCS, rules, build, wheel verification, repository validation, and secret scan.
4. Existing branch-specific GCS acceptance may remain skipped under its unchanged condition.
5. Exact step and total durations are recorded. If the job reaches 60 minutes or exposes a real
   failure, stop with the corresponding non-success status.

## G. Preservation and evidence

1. PR #16 remains open, based on `main`, at LIVE-ODDS head
   `5e55cf3361a1abff4b2e32dcc30fe42900ea2e16` and is not modified or rerun.
2. Evidence records bounded summaries and hashes, not large logs.
3. Only the exact authorized PRC-013 current manifest may change cross-ticket.
4. P0, P1, and material in-scope P2 findings are zero before engineering readiness.
5. Final status may be `ENGINEERING_READY_PENDING_INDEPENDENT_GOVERNANCE_REVIEW`; acceptance and
   merge remain separate.
