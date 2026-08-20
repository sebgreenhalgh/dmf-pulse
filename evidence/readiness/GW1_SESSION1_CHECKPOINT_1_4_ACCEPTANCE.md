# GW1 Checkpoint 1.4B Focused Validation

- Workflow run — `32399774975`
- Validated commit — `3ef25343725aeef1ebb3546a78e63a2ff72ea2e8`
- Branch — `readiness/GW1-2026-27-live-input-initial-squad`
- Commit subject — `docs: record market-primary Linux validation`
- Overall — `PASS`
- PostgreSQL — `NOT_EXECUTED` (transient/DB-free identity architecture).
- Real credentialled provider call — `OPERATOR_CHECKPOINT`.
- Checkpoint 1.5 work — `NOT_EXECUTED`.

## Exit codes

- `install_uv` — `PASS` (exit `0`)
- `frozen_sync` — `PASS` (exit `0`)
- `focused_pytest` — `PASS` (exit `0`)
- `ruff_format` — `PASS` (exit `0`)
- `ruff_format_diff` — `PASS` (exit `0`)
- `ruff_lint` — `PASS` (exit `0`)
- `strict_mypy` — `PASS` (exit `0`)
- `build` — `PASS` (exit `0`)
- `secret_scan` — `PASS` (exit `0`)
- `diff_check` — `PASS` (exit `0`)

## focused_pytest

```text
........................................................................ [ 41%]
........................................................................ [ 83%]
............................                                             [100%]
172 passed in 3.34s
```

## ruff_format

```text
4 files already formatted
```

## ruff_format_diff

```text
4 files already formatted
```

## ruff_lint

```text
All checks passed!
```

## strict_mypy

```text
Success: no issues found in 2 source files
```

## build

```text
Building source distribution...
Building wheel from source distribution...
Successfully built dist/dmf_pulse-0.2.0.tar.gz
Successfully built dist/dmf_pulse-0.2.0-py3-none-any.whl
```

## secret_scan

```text
{
  "finding_count": 0,
  "findings": [],
  "status": "PASS"
}
```

## diff_check

```text
```
