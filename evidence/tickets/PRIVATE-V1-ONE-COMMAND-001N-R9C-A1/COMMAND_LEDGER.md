# R9C-A1 command ledger

- `uv run python -m pytest tests/unit/private_v1/test_a1_allocation_injection.py -q`
  — PASS (8).
- `uv run python -m pytest tests/unit/private_v1/test_a1_shadow_adapter.py -q`
  — PASS (3).
- Combined A1, rolling and R9B synthetic regression — PASS (62).
- `uv run ruff check` / `uv run ruff format --check` / strict mypy — PASS.
- `uv run python scripts/validate_repository.py` and repository manifest tests — PASS.

No network or live execution command appears in this ledger.

## A1.03

- `uv run python -m pytest tests/unit/private_v1/test_a1_03_shadow_comparison.py -q`
  - PASS (2; real four-world canonical rolling comparison shared by the
  module-scoped fixture).
- `uv run python scripts/compare_r9c_a1_three_gw_shadow.py` - PASS; prints
  only synthetic aggregate comparison evidence and writes no result file.
- `uv run ruff check` / `uv run ruff format --check` / strict source mypy /
  `git diff --check` - PASS.
- `uv run python -m pytest tests/unit/private_v1/test_a1_allocation_injection.py`
  `tests/unit/private_v1/test_a1_shadow_adapter.py`
  `tests/unit/private_v1/test_a1_03_shadow_comparison.py -q` - PASS (13 in
  161.56 seconds).

## A1.03 review remediation (pre-artifact checkpoint)

- History-window resolver plus adapter regression: PASS (8).
- A1.01/A1.02/history/rolling regression: PASS (20 in 163.71 seconds).
- Real root-sensitive, real continuation-sensitive, sealing and reverse-order
  comparison regression: PASS (5 in 119.76 seconds).
- Changed production source Ruff and strict mypy: PASS.
- No provider, credential, private entry, persistence, training or activation
  command was executed.
- Implementation checkpoint: `6612c386118a8d5c0b8be3da5c3b3b45210608aa`.
- Generated root-sensitive and continuation-sensitive artifacts in parallel
  using the offline repository script and that exact implementation SHA.
- Independently regenerated both artifacts: artifact and comparison semantic
  hashes exact-equal; file bytes intentionally differ only in non-semantic
  diagnostic timings.
- R9B/Stage-9 focused regression: PASS (93 in 26.75 seconds).
- Exact Stage-10/Stage-11 focused regression: PASS (221 in 35.26 seconds).
- Complete `tests/unit/private_v1`: PASS (185 in 879.55 seconds).
- Changed-module branch coverage acceptance: PASS (91% aggregate; comparison
  95%, adapter 92%, rolling 88%, with inherited rolling misses disclosed).
- Full Ruff format/check, strict mypy (293 source files), frozen sync, build,
  validator, manifest tests (4), secret scan and `git diff --check`: PASS.
- Clean wheel import and CLI help: PASS outside the source tree with the frozen
  Typer 0.27.0 lock. An unconstrained install selected Typer 0.27.2 and failed
  CLI import; that non-frozen dependency result is not represented as a pass.
- Independent review found stale non-existent ticket authority aliases
  `A10-tactical` and `A11-rolling`. Remediation maps the ticket to the canonical
  `A9-points`, `A10-one-GW-optimiser`, `A11-decision-bundle`, and `B2-multi-GW`
  scopes; no code, model, optimizer, artifact or runtime semantics changed.

## A1.02-CI-R1

- Reproduced the two failing static guard tests: FAIL as expected on A1.02.
- `pytest tests/unit/ingestion/test_horizon_probe.py`
  `tests/unit/ingestion/test_horizon_rights_approval.py` — PASS (102).
- A1/R9B/rolling focused regression — PASS (66).
