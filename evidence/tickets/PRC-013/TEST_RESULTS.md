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

## Final main integration

- Integrated Stage-13 suite: **PASS**, 116 tests; **90.56%** branch-aware coverage.
- Preserved inherited selectors: **PASS**, 17 tests in 1.12 seconds.
- Current-main rules/Stage-11 integration batch: **PASS**, 104 tests in 5.50 seconds.
- Post-integration full repository pytest: **RESOURCE_LIMIT** at 1204 seconds without a final
  summary or emitted failure trace; not rerun and not PASS.
