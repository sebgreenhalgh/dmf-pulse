# GW1 Checkpoint 1.3B Final Remediation Validation

- Workflow run — `32247073642`
- Original failing workflow — `32194395276`
- First remediation workflow — `32246327083` (`FAIL`)
- Exact startup remote SHA — `7df6483a461e4cf2917c70b27aa52d75cac39822`
- Remediation commit — `03b76f08bb1648359e1c63a3c1d4ae4ea5d58f79`
- Branch — `readiness/GW1-2026-27-live-input-initial-squad`
- Overall — `PASS`
- Real credentialled provider call — `OPERATOR_CHECKPOINT`

## Root causes and final resolution

- CLI: preserved the accepted `schema_version` / `status` / `error` envelope and corrected the stale test.
- Lifecycle ordering: restored `MAPPED` and `PROMOTED` before `QUALITY_PASSED`, with explicit provider-native/no-canonical-mapping semantics.
- Snapshot immutability: removed the prohibited post-receipt `source_snapshot` update; final status is derived from append-only processing events and `source_snapshot_lifecycle`.
- Ruff: fixed import ordering and imported `Callable` from `collections.abc`; no suppressions were added.

## Results

- `focused_pytest` — `PASS` (exit `0`)
- `inherited_odds_pytest` — `PASS` (exit `0`)
- `affected_cli_pytest` — `PASS` (exit `0`)
- `postgres_integration` — `PASS` (exit `0`)
- `ruff_format` — `PASS` (exit `0`)
- `ruff_lint` — `PASS` (exit `0`)
- `strict_mypy` — `PASS` (exit `0`)
- `wheel_build` — `PASS` (exit `0`)
- `secret_scan` — `PASS` (exit `0`)
- `diff_check` — `PASS` (exit `0`)

## focused_pytest output

```text
................................................................         [100%]
64 passed in 3.59s
```

## inherited_odds_pytest output

```text
........................................................................ [ 69%]
...............................                                          [100%]
103 passed in 3.02s
```

## affected_cli_pytest output

```text
.............................                                            [100%]
29 passed in 3.00s
```

## postgres_integration output

```text
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 20260723_0001, Create the DAT-003 canonical temporal PostgreSQL foundation.
INFO  [alembic.runtime.migration] Running upgrade 20260723_0001 -> 20260724_0002, Remediate DAT-003 and add the FPL-004 ingestion foundation.
INFO  [alembic.runtime.migration] Running upgrade 20260724_0002 -> 20260725_0003, Bind FPL bundles to authoritative rights and persisted quality.
INFO  [alembic.runtime.migration] Running upgrade 20260725_0003 -> 20260725_0004, Add canonical operators, markets, exact odds, and quota evidence.
INFO  [alembic.runtime.migration] Running upgrade 20260725_0004 -> 20260803_0005, NRM-006 post-commit odds publication and normalisation persistence.
INFO  [alembic.runtime.migration] Running upgrade 20260803_0005 -> 20260807_0006, MIN-007F immutable availability registry and prediction persistence.
.                                                                        [100%]
1 passed in 0.54s
```

## ruff_format output

```text
7 files already formatted
```

## ruff_lint output

```text
All checks passed!
```

## strict_mypy output

```text
Success: no issues found in 3 source files
```

## wheel_build output

```text
Building source distribution...
Building wheel from source distribution...
Successfully built dist/dmf_pulse-0.2.0.tar.gz
Successfully built dist/dmf_pulse-0.2.0-py3-none-any.whl
```

## secret_scan output

```text
{
  "finding_count": 0,
  "findings": [],
  "status": "PASS"
}
```

## diff_check output

```text
```

## Rights, storage and identity

- Runtime credential-provider wiring remains unchanged; no API-key CLI option exists.
- Raw provider payload retention remains forbidden; no raw blob/object or canonical market/odds rows are created by the provider-native path.
- Public display, redistribution, backup and model training remain denied by the active Rights Profile.
- Canonical FPL fixture/team mapping and fuzzy matching remain unperformed.
- The immutable source receipt row remains `RECEIVED`; append-only lifecycle evidence derives the final `USABLE` state.

## Scope and handoff

- Checkpoint 1.3B — `COMPLETE`.
- Checkpoint 1.3C — `NOT_STARTED`.
- Checkpoint 1.4 — `INCOMPLETE` / `NOT_STARTED`.
- Exact next action — **CHECKPOINT 1.3C — CHECKPOINT ACCEPTANCE / OPERATOR CONTRACT**.
