# CI-TEST-002 acceptance contract

This contract authorizes only the DIAG-02 evaluation CLI test-observation correction. It does not
authorize production, CLI rendering, workflow, timeout, coverage, dependency, CI-FPL,
CI-TEST-001, LIVE-ODDS, PR #16, merge or human-acceptance changes.

## A. Git and scope

1. The branch starts at exact parent `d550250836c9c39e6caebaa5f12ad94fec7e2b02` and is named
   `remediation/CI-TEST-002-evaluation-cli-ansi-contract`.
2. Diagnostic commit `6fdcad8153897e7485ac48fcc6409008a24e8274` remains separate and is
   not cherry-picked.
3. Only the ticket allowlist changes, including the exact PRC-013 current-manifest exception when
   canonical repository tooling requires it.

## B. Semantic CLI contract

1. The existing global runner, application object, test function, six commands, command order,
   invocation, `--output yaml`, exit-code assertion and message wording remain unchanged.
2. Terminal styling remains enabled. The test normalizes ANSI only after invocation and only for
   the semantic message comparison.
3. Every command exits 2 and normalized output contains `--output must be json`.
4. No durable assertion depends on a specific ANSI escape sequence, color or terminal width.
5. The frozen dependency graph is unchanged. Because it contains no Click distribution, the test
   uses the existing Rich 15 public API `Text.from_ansi(...).plain` rather than adding Click.

## C. Required validation

The target passes on Windows in baseline, `CI=true`, `GITHUB_ACTIONS=true`, and combined states.
The target and module pass on Windows and Linux Python 3.13 with `GITHUB_ACTIONS=true`; the module
passes targeted branch-coverage instrumentation with `--cov-fail-under=0` without changing any
repository threshold.

Diff, Ruff, repository validation, secret scanning, ticket evidence, repository manifests and
exact-scope checks pass. Automatic GitHub CI shows the evaluation module green before the
unchanged monolithic timeout.

## D. Truthful completion

The maximum bounded status is
`TEST_FIX_READY_PENDING_INDEPENDENT_REVIEW_WITH_KNOWN_EXTERNAL_CI_ARCHITECTURE_BLOCKER`.
Independent review, human acceptance, merge and full-CI-green status are not claimed.
