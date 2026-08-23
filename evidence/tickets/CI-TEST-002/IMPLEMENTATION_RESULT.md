# CI-TEST-002 implementation result

Local status:
`TEST_FIX_READY_PENDING_INDEPENDENT_REVIEW_WITH_KNOWN_EXTERNAL_CI_ARCHITECTURE_BLOCKER`

## Change

Only `tests/contract/evaluation/test_cli_contract.py` changes executable behavior. Immediately
after the existing invocation, `rich.text.Text.from_ansi(result.output).plain` derives semantic
plain text. The existing exit-code assertion and exact `--output must be json` expectation then
apply in their original order. All six commands remain in the original loop.

Click was checked first but is absent from the frozen 40-package dependency graph. Rich 15 is the
existing direct Typer dependency, and its public ANSI decoder avoids a dependency or lock change.

## Trigger and environment results

On Windows CPython 3.13.9 the target passed in all four real process states:

- baseline: `1 passed in 3.75s`;
- `CI=true`: `1 passed in 3.70s`;
- `GITHUB_ACTIONS=true`: `1 passed in 3.65s`;
- combined: `1 passed in 3.75s`.

The bounded first-command probe under `GITHUB_ACTIONS=true` recorded exit code 2, raw expected
literal false and normalized expected literal true. The raw output retained ANSI styling.

The complete module passed `6 passed in 5.29s` on Windows baseline and `6 passed in 5.28s` with
`GITHUB_ACTIONS=true`. The styled targeted coverage invocation passed `6 passed in 19.84s`; the
evaluation CLI implementation was measured at 100% without changing repository thresholds.

In a disposable Debian bookworm container, CPython 3.13.15 with `GITHUB_ACTIONS=true` passed the
target (`1 passed in 8.13s`) and module (`6 passed in 7.48s`) against a read-only repository mount.

Ruff format/check, strict production typing, secret scanning, evidence validation and exact scope
checks passed. Repository validation completed through the validator's read-only function with
zero errors; its literal wrapper was not invoked because it would write an unauthorized GCS-008
report.

## Confinement

- Product source changed: no.
- CLI behavior or wording changed: no.
- Rich rendering changed: no.
- Workflow, timeout or coverage configuration changed: no.
- Dependency or lock changed: no.
- Configuration or migration changed: no.
- CI-TEST-001, CI-FPL, LIVE-ODDS and PR #16 changed: no.

Automatic branch CI, independent review, human acceptance and merge are not claimed by this local
evidence snapshot.
