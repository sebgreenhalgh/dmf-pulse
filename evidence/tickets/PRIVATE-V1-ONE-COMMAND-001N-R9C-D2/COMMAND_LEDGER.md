# R9C-D2 command ledger

This ticket authorizes zero FPL/Odds requests, zero credential inspection, zero live
observations and zero recommendations. All validation is synthetic or repository-owned
frozen input. No probe command is executed.

Local acceptance and publication results will be added after completion.

Completed offline commands include:

```text
uv sync --all-groups --frozen
.venv\Scripts\python.exe -m pytest [focused D1/D2 probe tests]
.venv\Scripts\python.exe -m pytest [affected direct-FPL/private-shadow regressions]
.venv\Scripts\python.exe -m coverage run --branch --source=scripts -m pytest [focused]
.venv\Scripts\python.exe -m ruff check/format --check [changed files]
.venv\Scripts\python.exe -m mypy --strict scripts/probe_current_player_posterior_shadow.py
.venv\Scripts\python.exe scripts\replay_r7_frozen_service.py [parent and candidate]
.venv\Scripts\python.exe scripts\generate_repository_manifest.py --ticket PRC-013
.venv\Scripts\python.exe scripts\generate_repository_manifest.py --ticket PRIVATE-V1-ONE-COMMAND-001N-R9C-D2
.venv\Scripts\python.exe -m pytest tests/integration/repository/test_manifests.py tests/unit/assurance/test_manifests.py -q
.venv\Scripts\python.exe scripts\validate_repository.py
.venv\Scripts\python.exe scripts\scan_secrets.py
.venv\Scripts\python.exe -m build --wheel --no-isolation
.venv\Scripts\python.exe scripts\verify_r9b_wheel.py
```

The repository-owned frozen replay is synthetic. No command in this ledger invokes the
probe or `dmf pulse` against a provider.
