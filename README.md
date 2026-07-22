# DMF Pulse

DMF Pulse is a private FPL decision-engine project. FND-001 provides only its governed Python foundation: strict application configuration, the deterministic `dmf` CLI, offline system diagnostics, and first-party evidence/review tooling. It deliberately contains no FPL rules, data clients, database, models, optimisation, server, or UI.

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
uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing
```

## Linux, WSL2, or POSIX shell

```sh
uv sync --all-groups --frozen
uv run dmf --version
uv run dmf doctor --json
uv run dmf config validate --environment test --config-root config
uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing
```

Make is optional convenience only. The complete canonical quality sequence is:

```text
uv run ruff format --check .
uv run ruff check .
uv run mypy src/dmf_pulse
uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing
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
dmf review-pack build --ticket FND-001 --output <path>
```

Commands perform no provider/network/database access. Configuration loading never resolves a secret or creates the configured artifact directory. See `docs/operations/windows_and_linux_setup.md` for troubleshooting and `CONTRIBUTING.md` before changing dependencies or public contracts.
