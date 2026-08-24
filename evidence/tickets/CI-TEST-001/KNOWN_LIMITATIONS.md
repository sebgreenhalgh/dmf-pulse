# CI-TEST-001 known limitations

- The executable fix received a clean independent technical review on the historical parent
  `652bae84fba9bdfbf435367d6140270fa8378d57`; the new corrected-parent ancestry still requires
  independent lineage confirmation.
- The monolithic full coverage job remains unable to complete within its inherited 35-minute
  runtime. This reseal does not modify workflows, timeouts, sharding, or coverage configuration.
- `--cov-fail-under=0` was used only on the historical targeted module invocation so the unrelated
  repository-wide aggregate threshold would not mask the test result. No configured threshold
  changed.
- Historical Linux evidence used Debian Linux CPython 3.13.15 in a disposable container. The
  rebuilt stack is validated on the currently available Windows host unless otherwise recorded.
- Automatic branch CI, independent lineage confirmation, human acceptance, and merge remain
  pending at local evidence sealing time.
