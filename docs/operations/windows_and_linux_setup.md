# Windows and Linux setup

## Windows PowerShell

```powershell
git clone <private-repository-url>
Set-Location dmf-pulse
uv python install 3.13
uv sync --all-groups --frozen
uv run dmf doctor --json
uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing
```

## Linux, WSL2, or POSIX

```sh
git clone <private-repository-url>
cd dmf-pulse
uv python install 3.13
uv sync --all-groups --frozen
uv run dmf doctor --json
uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing
```

Use the uv/Python commands directly; Make targets only delegate. The package carries one
hash-pinned IANA TZif fallback for its `Europe/London` default so stock Windows Python does not
need an extra timezone dependency. Other display zones still require the host Python timezone
database. Runtime commands do not need network access.

For a complete local gate, run every command in `tickets/FND-001/ACCEPTANCE.md` literally. Generated builds, coverage, artifacts, and review packs are ignored; ticket evidence is retained.
