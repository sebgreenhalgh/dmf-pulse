# DMF Pulse

DMF Pulse is a private FPL decision-engine project. RUL-002 adds a governed, versioned rules foundation to the FND-001 Python package: strict split-YAML compilation, immutable lifecycle controls, configured BPS/bonus, and pure fixture/Gameweek scoring. It deliberately contains no provider client, database, forecasting model, optimiser, server, UI, or automatic FPL action.

## Requirements

- Python 3.13 compatibility
- [uv](https://docs.astral.sh/uv/) available on `PATH`
- Git (optional for parts of `dmf doctor`)

The project is proprietary and All Rights Reserved. Approved architecture documents live under `specs/approved/`; their exact hashes are enforced by `specs/manifests/document_manifest.json`.

## Windows PowerShell

```powershell
uv sync --all-groups --frozen
uv run dmf --version
uv run dmf doctor --json
uv run dmf config validate --environment test --config-root config
uv run dmf rules validate fixtures/rules/RUL-002/synthetic_complete --json
uv run dmf rules compile fixtures/rules/RUL-002/synthetic_complete --output artifacts/rules/rul-002-synthetic.json --json
uv run dmf rules score-fixture artifacts/rules/rul-002-synthetic.json fixtures/rules/RUL-002/golden_fixture_001.json --json
uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/RUL-002/coverage.json
uv run python scripts/check_coverage_gates.py
```

## Linux, WSL2, or POSIX shell

```sh
uv sync --all-groups --frozen
uv run dmf --version
uv run dmf doctor --json
uv run dmf config validate --environment test --config-root config
uv run dmf rules validate fixtures/rules/RUL-002/synthetic_complete --json
uv run dmf rules compile fixtures/rules/RUL-002/synthetic_complete --output artifacts/rules/rul-002-synthetic.json --json
uv run dmf rules score-fixture artifacts/rules/rul-002-synthetic.json fixtures/rules/RUL-002/golden_fixture_001.json --json
uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/RUL-002/coverage.json
uv run python scripts/check_coverage_gates.py
```

Make is optional convenience only. The complete canonical quality sequence is:

```text
uv run ruff format --check .
uv run ruff check .
uv run mypy src/dmf_pulse
uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/RUL-002/coverage.json
uv run python scripts/check_coverage_gates.py
uv build
uv run python scripts/verify_wheel.py
uv run python scripts/validate_repository.py
uv run python scripts/scan_secrets.py
```

Ubuntu CI runs on every push and pull request. Windows uses a monthly scheduled/manual smoke workflow so private-repository minutes are spent on portability checks without duplicating the complete required Ubuntu gate.

## CLI

```text
dmf --version
dmf doctor [--json]
dmf config validate --environment <name> --config-root <path>
dmf config show --environment <name> --config-root <path> [--json]
dmf evidence validate <path>
dmf rules validate SOURCE_DIR [--json]
dmf rules compile SOURCE_DIR --output FILE [--json]
dmf rules hash COMPILED_FILE [--json]
dmf rules show RULESET [--json]
dmf rules diff LEFT RIGHT [--json]
dmf rules score-fixture RULESET SCENARIO [--json]
dmf rules score-gameweek RULESET SCENARIO [--json]
dmf rules activate RULESET --approval APPROVAL [--registry DIRECTORY] [--json]
dmf review-pack build --ticket RUL-002 --baseline <commit> --output <path>
```

Commands perform no provider/network/database access. Scoring is pure and always identifies the exact compiled ruleset hash. The partial 2026/27 target may validate, compile, show, and diff, but unresolved families make scoring and activation fail closed. See `docs/rules/README.md`, `docs/operations/windows_and_linux_setup.md`, and `CONTRIBUTING.md` before changing rules, dependencies, or public contracts.
