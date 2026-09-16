# R9C-D1 command ledger

No live FPL/Odds request, credential inspection, live probe or recommendation is
authorized in this ticket. All tests use fakes and repository-owned synthetic inputs.

Completed local commands:

```text
uv sync --all-groups --frozen
uv run python -m pytest tests/unit/fpl_points/test_current_player_shadow_operations.py tests/unit/fpl_points/test_shadow_probe_failure_diagnostics.py -q
uv run python -m coverage run --branch --source=scripts -m pytest ...
uv run python -m coverage report --include='*probe_current_player_posterior_shadow.py' --show-missing --fail-under=90
uv run ruff check scripts/probe_current_player_posterior_shadow.py tests/unit/fpl_points/test_shadow_probe_failure_diagnostics.py
uv run python -m mypy scripts/probe_current_player_posterior_shadow.py
uv run python scripts/generate_repository_manifest.py --ticket PRC-013
uv run python scripts/generate_repository_manifest.py --ticket PRIVATE-V1-ONE-COMMAND-001N-R9C-D1
uv run python -m pytest tests/integration/repository/test_manifests.py tests/unit/assurance/test_manifests.py -q
uv run python scripts/validate_repository.py
.venv\\Scripts\\python.exe scripts\\scan_secrets.py
.venv\\Scripts\\python.exe scripts\\replay_r7_frozen_service.py --code-root ../one-command-n-r9b ...
.venv\\Scripts\\python.exe scripts\\replay_r7_frozen_service.py --code-root . ...
.venv\\Scripts\\python.exe -m build --wheel --no-isolation
.venv\\Scripts\\python.exe scripts\\verify_r9b_wheel.py
```

The local `pytest` launcher is blocked by Windows Application Control (4551); the
equivalent trusted `uv run python -m pytest` invocation is used. No validation command
executes the live probe. A standard isolated build attempted to fetch the pinned build
backend and was blocked by local network policy; the existing synced backend completed
the no-isolation build. The clean wheel verifier was network-disabled and passed after
scoped local child-process permission. Independent review, publication and CI remain
pending.
