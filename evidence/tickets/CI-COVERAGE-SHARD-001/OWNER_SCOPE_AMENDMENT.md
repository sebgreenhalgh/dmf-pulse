# CI-COVERAGE-SHARD-001 owner scope amendment

Owner-authorized amendment date: `2026-08-24`

Ticket: `CI-COVERAGE-SHARD-001`

Status: `OWNER_SCOPE_AMENDMENT_SUPPLIED_PENDING_INDEPENDENT_CONFIRMATION`

## Chronology and authority

The original implementation instruction limited substantive work to CI execution architecture.
Independent review of reviewed state `b8ce5de612d835bee6721898cd57e46c133f90dd` therefore raised
GOV-001: the implementation-edited ticket could not itself supply owner authority for two inherited
test paths.

After that review, the repository owner explicitly supplied this amendment. It ratifies the exact
existing assertion-observation changes introduced in commit
`4da506d8fa4c00a61c5387f66b94e8c2d15a4c7b` and retained unchanged at reviewed state
`b8ce5de612d835bee6721898cd57e46c133f90dd`.

Exact ratified paths:

- `tests/unit/cli/test_rank_cli.py`
- `tests/unit/optimisation/test_multi_gameweek_cli_hardening.py`

## Exact authorized semantic scope

Authorization is limited to importing Rich's existing public `Text` API, applying
`Text.from_ansi(...).plain` at the existing test observation boundary, and applying the existing
`--output must be json` substring assertion to that normalized text.

For rank CLI, the observation remains `stdout + stderr` and the existing non-zero failure
expectation and command coverage remain unchanged. For optimisation CLI, the observation remains
`result.output`, the required exit code remains `2`, and command coverage remains unchanged.

## Explicit exclusions

This amendment does not authorize any product or production CLI change, command or argument
change, exit-code or message change, Rich/ANSI/color suppression, `GITHUB_ACTIONS` suppression,
skip, xfail, retry, marker change, dependency change, broader edit to either ratified file, or any
other scope expansion.

This record preserves the true order: original scope was narrower, independent review identified
GOV-001, and the owner then ratified only the two exact existing deltas. Independent confirmation
of closure remains pending.
