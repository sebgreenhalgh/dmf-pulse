# PRC-013 test results

- Stage-13 focused suite with final branch coverage: **PASS**, 112 tests.
- Stage-13 branch-aware coverage: **PASS**, 90.57% (required >=90%).
- Targeted inherited dependency regressions: **PASS**, 17 tests.
- Physical fixtures: 20 required adversarial cases, 7 ordinary/replay cases and 5 independent
  review cases (32 unique cases total).
- Network: disabled by the inherited autouse test boundary.
- Full repository pytest: **RESOURCE_LIMIT**; the single complete run reached the 20-minute
  execution ceiling without a final summary or emitted failure trace. It was not rerun unchanged.

Exact final commands and environment limitations are retained in `COMMAND_LEDGER.md`.
