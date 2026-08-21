# GW1-PLY-002 acceptance

This ticket is a candidate-only bounded calibration. Human review must verify
the source licence, attribution, historical-scope limitation, the coarse
role/FPL-position fallback, every unsupported field, and the non-adoption of
fitted kappa before it can be used for private GW1 decision support.

Required offline checks:

```text
uv run pytest -q tests/unit/player_evidence tests/unit/fpl_points/test_allocation.py tests/unit/fpl_points/test_current_football_events.py
uv run ruff format --check src/dmf_pulse tests scripts
uv run ruff check src/dmf_pulse tests scripts
uv run mypy src/dmf_pulse
uv run python scripts/validate_repository.py
uv run python scripts/scan_secrets.py
uv build
```

The dedicated workflow must not contact Figshare; it uses only the committed
aggregate artifact and synthetic fixtures. The raw CC-BY files are deliberately
not committed.

This ticket does not accept official-FPL history rights, capture history,
player allocation, or production activation.
