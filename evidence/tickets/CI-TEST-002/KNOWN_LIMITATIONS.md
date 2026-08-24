# CI-TEST-002 known limitations

- The executable fix received a clean independent technical review on historical parent
  `d550250836c9c39e6caebaa5f12ad94fec7e2b02`; rebuilt ancestry requires independent lineage
  confirmation.
- The monolithic full coverage workflow remains unable to complete within its unchanged 35-minute
  budget. This reseal does not change workflow architecture, timeouts, sharding, or coverage.
- `--cov-fail-under=0` was used only by the historical targeted module invocation; no repository
  threshold changed.
- Historical Linux evidence used Debian bookworm CPython 3.13.15 with a read-only repository
  mount. The rebuilt stack is validated on the available Windows host unless otherwise recorded.
- Independent lineage confirmation, human acceptance and merge remain pending.
