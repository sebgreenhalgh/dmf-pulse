# R9C-D2 test results

All results are local, synthetic and offline. No live probe is represented.

- Probe operations, D1 diagnostics and D2 acquisition trace: 23 passed.
- Changed probe branch coverage: 96% (190/198 lines; all measured branches covered).
- Affected direct-FPL/private-shadow regression: 215 passed, zero failures/errors.
- Source-isolated frozen R9C-D1/R9C-D2 active-path replay: equal execution and
  projection hashes; only wall/CPU timing differs.
- Ruff and strict mypy: passed.
- Repository-manifest tests: 8 passed; repository validator and secret scan: PASS.
- No-isolation wheel build and clean installed-wheel synthetic verifier: PASS, with
  zero provider requests and historical resource hash
  `ca3084edded94fda8b0818f4277aca335f25e8112bb9379f47c11c2ad4b29909`.

Independent review and exact-SHA CI remain pending.
