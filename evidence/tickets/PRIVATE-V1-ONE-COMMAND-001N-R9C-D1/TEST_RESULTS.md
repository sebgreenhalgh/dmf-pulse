# R9C-D1 test results

All results below are local, synthetic and offline; no live execution is represented.

- Focused R9C-D1 plus inherited probe operations: 15 passed.
- Changed probe branch coverage: 95% (151/159 lines; all measured branches covered).
- Strict mypy for the changed probe: passed.
- Ruff check for changed probe/tests: passed.

- Broader R9A/R9B/rights/private-command regression: 165 passed, 0 failed, 0 errors
  (264.079 seconds).
- Repository-manifest tests: 8 passed.
- Repository validator and first-party secret scan: PASS, zero findings/errors.
- Frozen source-isolated R9B/R9C-D1 replay: exact-equal execution and projection hashes;
  only measured wall/CPU time differs.
- Offline no-isolation wheel build: passed. The repository clean installed-wheel synthetic
  verifier: passed, with zero provider requests.

Exact-SHA CI is not claimed before publication.
