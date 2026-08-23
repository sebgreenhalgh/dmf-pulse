# CI-TEST-001 known limitations

- DIAG-02 remains unresolved. Its CI progress marker was observed, but the cancelled job did not
  emit the exact failing loop command, actual value, or terminal traceback. This ticket does not
  alter evaluation tests or CLI code.
- The monolithic full coverage job remains unable to complete within its current bounded runtime.
  This ticket does not modify workflows, timeouts, sharding, or coverage configuration.
- `--cov-fail-under=0` was used only on the required targeted module invocation so the unrelated
  repository-wide aggregate threshold would not mask the test result. No configured threshold
  changed.
- Linux evidence uses Debian Linux CPython 3.13.15 in a disposable container rather than a new
  GitHub-hosted Ubuntu run. The repository was mounted read-only and the frozen lock was used.
- Automatic branch CI, independent review, human acceptance, and merge remain pending at local
  evidence sealing time.
