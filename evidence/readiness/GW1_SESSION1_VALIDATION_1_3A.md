# GW1 Checkpoint 1.3A Focused Validation

- Workflow run — `32192196539`
- Validated commit — `f23396a6d254cf681da0816f739dc3dc4428cebb`
- Branch — `readiness/GW1-2026-27-live-input-initial-squad`
- Overall — `PASS`
- Real credentialled provider call — `OPERATOR_CHECKPOINT`

## Exit codes

- `install_uv` — `PASS` (exit `0`)
- `frozen_sync` — `PASS` (exit `0`)
- `focused_pytest` — `PASS` (exit `0`)
- `ruff_format` — `PASS` (exit `0`)
- `ruff_lint` — `PASS` (exit `0`)
- `strict_mypy` — `PASS` (exit `0`)
- `secret_scan` — `PASS` (exit `0`)
- `diff_check` — `PASS` (exit `0`)

## Focused pytest output

```text
...........                                                              [100%]
11 passed in 2.08s
```

## Secret scan output

```json
{
  "finding_count": 0,
  "findings": [],
  "status": "PASS"
}
```
