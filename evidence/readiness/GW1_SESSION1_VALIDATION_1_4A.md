# GW1 Checkpoint 1.4A Focused Validation

- Workflow run — `32281153327`
- Validated commit — `a5bdc995080dc984676133c1f70c7a2bc0594801`
- Branch — `readiness/GW1-2026-27-live-input-initial-squad`
- Commit subject — `fix(gw1): satisfy team identity validation gates`
- Overall — `FAIL`
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
- `diff_check` — `FAIL` (exit `2`)

## focused_pytest

```text
........................................................................ [ 57%]
......................................................                   [100%]
126 passed in 2.79s
```

## ruff_format

```text
3 files already formatted
```

## ruff_format_diff

```text
3 files already formatted
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
evidence/readiness/GW1_SESSION1_VALIDATION_1_4A.md:57: trailing whitespace.
+ 
evidence/readiness/GW1_SESSION1_VALIDATION_1_4A.md:84: trailing whitespace.
+ 
evidence/readiness/GW1_SESSION1_VALIDATION_1_4A.md:102: trailing whitespace.
+ 
```
