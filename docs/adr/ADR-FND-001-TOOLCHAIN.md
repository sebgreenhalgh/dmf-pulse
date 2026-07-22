# ADR-FND-001: Foundation toolchain realization

- Status: SANCTIONED FOR FND-001; `ADR-IMPL-002` remains PROVISIONAL
- Date: 2026-07-22

## Decision

Use Python 3.13, uv, Hatchling, `dmf-pulse`/`dmf_pulse`, Typer, Pydantic v2, and PyYAML. Use Ruff, mypy, pytest, Hypothesis, coverage, and build for development. The runtime baseline is CPU; optional GPU discovery is `nvidia-smi` only. Use GitHub Actions with required Ubuntu CI and scheduled/manual Windows smoke.

## Consequences

The exact resolved versions live in `uv.lock`; imports remain side-effect free; no database, numerical/ML/GPU, provider, API-server, solver, or other future-stage dependency is installed. The repository is proprietary and All Rights Reserved.

This record implements pack-sanctioned choices; it does not upgrade the provisional DMFP-20 toolchain decision to accepted.
