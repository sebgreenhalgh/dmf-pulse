# D5 offline acceptance

## Test populations

- Stage-11 unit/golden population: 369 passed in 539.96 seconds.
- D1/D2/D3/D4, L1/L2 authority and private one-command regressions: 344 passed
  in 2187.67 seconds.
- Stage-8/Stage-9 unit and golden regressions: 499 passed, 1 deselected in
  79.61 seconds.
- Focused terminal D1-D4 seam: 2 passed in 178.32 seconds.
- Independent focused population: 372 passed in 1211.63 seconds.
- Refreshed five-case 001P oracle: A/B/C/D/E all PASS; 10/10 world solves
  SUCCESS; provider calls 0.
- Generated near-envelope proof: legacy 250,000 typed failure at 250,036;
  524,288 and 1,048,576 both SUCCESS at 320,610 with identical decision
  semantic SHA.

## Quality and packaging

- `uv sync --all-groups --frozen`: PASS, 40 packages checked.
- `uv run ruff format --check .`: PASS, 909 files formatted.
- `uv run ruff check .`: PASS.
- `uv run mypy src/dmf_pulse`: PASS, 313 source files.
- `uv build`: PASS; wheel and source distribution built.
- installed-wheel team-strength authority/diagnostic verification: PASS,
  provider calls 0.
- `dmf specs validate`: PASS, 94 decisions / 22 documents / 19 scopes.
- test configuration validation: PASS.
- repository validator after canonical manifest regeneration: PASS.
- first-party secret scan: PASS, zero findings.
- `git diff --check`: PASS.
- exact-SHA CI: required after final publication; the immutable remote result is
  reported in the final handoff rather than changing this commit afterward.

## Invariants

- official FPL requests: 0;
- The Odds API requests: 0;
- live OpenFootball requests: 0;
- credential inspection: none;
- L1/L2/L3/L4/L5: consumed;
- current live authority: none;
- L6 authority: absent;
- candidate scope: unchanged;
- exactness guarantee: unchanged;
- team strength: shadow only;
- production activation: false.
