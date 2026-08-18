# GW1 Checkpoint 1.3A Focused Validation

- Workflow run — `32191636148`
- Validated commit — `a318175ec82d39df7458d9dc003a5a54a481827a`
- Branch — `readiness/GW1-2026-27-live-input-initial-squad`
- Overall — `FAIL`
- Real credentialled provider call — `OPERATOR_CHECKPOINT`

## Exit codes

- `install_uv` — `PASS` (exit `0`)
- `frozen_sync` — `PASS` (exit `0`)
- `focused_pytest` — `PASS` (exit `0`)
- `ruff_format` — `PASS` (exit `0`)
- `ruff_lint` — `PASS` (exit `0`)
- `strict_mypy` — `PASS` (exit `0`)
- `secret_scan` — `FAIL` (exit `1`)
- `diff_check` — `PASS` (exit `0`)

## Focused pytest output

```text
...........                                                              [100%]
11 passed in 1.98s
```
