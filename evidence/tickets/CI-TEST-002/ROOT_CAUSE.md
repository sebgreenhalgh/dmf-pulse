# CI-TEST-002 root cause

Classification: `TEST_OBSERVATION_DEFECT`

The evaluation CLI contract failure recurred in uninstrumented GitHub runs `32600781430` and
`32645768494` as `tests/contract/evaluation/test_cli_contract.py ...F..`. Dedicated diagnostic
commit `6fdcad8153897e7485ac48fcc6409008a24e8274` and run `32649658465` reproduced the same marker
and isolated `GITHUB_ACTIONS=true` as the trigger.

For the first command, `evaluate build-folds`, the result continued to exit 2 with
`SystemExit(2)` and visibly report `--output must be json`. Typer detects `GITHUB_ACTIONS` and
forces Rich terminal rendering. Rich styling separates the two option-name dashes with ANSI
control sequences, so raw literal containment is false even though the human-visible semantic
message is correct.

The evaluation service, CLI validation, exit code, wording and Rich rendering are correct and are
not changed. The remediation converts `result.output` to plain semantic text only at assertion
time, then applies the same expected-message assertion.

The ticket proposed Click's public `unstyle` API, conditional on availability. The repository's
frozen 40-package graph contains Typer 0.27 and Rich 15 but no Click distribution; importing Click
fails. Adding a dependency is forbidden. The equivalent existing public API
`rich.text.Text.from_ansi(result.output).plain` is therefore used without changing the lock.
