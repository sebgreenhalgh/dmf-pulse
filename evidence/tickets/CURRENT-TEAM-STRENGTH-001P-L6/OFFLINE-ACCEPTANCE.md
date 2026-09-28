# L6 Phase A offline acceptance

## Public readiness and exactness

- September 28 immutable OpenFootball acquisition/validation/refit: `FRESH`,
  `LIVE_OBSERVED`, 50/50 due fixtures scored, zero missing, 380 registrations,
  42 fitted clubs, zero FPL/Odds requests.
- Five accepted 001P cases: A/B/C/D/E all `PASS`; provider calls zero.
- D5 near-envelope rerun: 250,000 produced typed
  `CUMULATIVE_LEGAL_ACTION_LIMIT` / no-incumbent failure at 250,036; 524,288
  and 1,048,576 both succeeded at 320,610 with identical full decision SHA
  `f5b3d892d999e399be67c6137726adb54d136ccc73a40699b19f5d1efe5e2f47`.

## Test populations

- L6 authority, rights, CLI and live-wrapper focused population: 129 passed in
  511.10 seconds.
- Final L6 authority/cap/evidence population: 61 passed in 2.08 seconds.
- D1-D5, rolling, two-world, ordinary one-command and service regressions: 366
  passed in 3,191.09 seconds.
- Stage 10/11, model, adapter and public OpenFootball team-strength regressions:
  691 passed in 500.11 seconds.
- Repository performance population: 4 passed, 5,466 deselected in 23.56
  seconds. The inherited Pydantic serialization warning is unchanged.
- Full repository branch-coverage and performance populations are required from
  mandatory exact-SHA CI; local results above are the risk-focused offline suite.

## Quality and packaging

- `uv sync --all-groups --frozen`: PASS, 40 packages checked.
- `uv run ruff format --check .`: PASS, 910 files formatted.
- `uv run ruff check .`: PASS.
- `uv run mypy src/dmf_pulse`: PASS, 313 source files.
- wheel and source distribution build: PASS.
- clean external installed-wheel L6 authority/diagnostic verification: PASS,
  provider calls 0.
- `dmf specs validate`: PASS, 94 decisions / 22 documents / 19 scopes.
- `dmf --version`: `0.2.0`; doctor: `HEALTHY`; test configuration validation
  and sanitized JSON display: PASS.
- first-party secret scan: PASS, zero findings.
- `git diff --check`: PASS.
- canonical PRC-013 and L6 manifests: generated for 1,548 repository files.
- repository validation: PASS, zero errors.
- fresh independent review: no P0, P1 or material P2; 87 focused checks passed;
  verdict `CLEAR_FOR_CURRENT_TEAM_STRENGTH_001P_L6_ONE_SHOT_EXECUTION`.
- capped deterministic review pack: PASS, 25 entries. Mandatory exact-SHA CI is
  required after the immutable final commit is published.

## Phase boundary

- Official FPL requests: 0.
- The Odds API requests: 0.
- Credential inspection: none.
- L1/L2/L3/L4/L5: permanently consumed.
- L6: current but not consumed.
- Team strength: `SHADOW_NOT_MODEL_INPUT`.
- Production activation: false.
