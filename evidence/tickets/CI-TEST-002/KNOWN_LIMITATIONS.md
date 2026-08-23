# CI-TEST-002 known limitations

- The monolithic full coverage workflow remains unable to complete within its unchanged
  35-minute budget. This ticket does not change workflow architecture, timeouts, sharding or
  coverage settings.
- `--cov-fail-under=0` is permitted only for the required targeted module invocation; no
  repository threshold changes.
- The diagnostic run's workflow reached its timeout before GitHub finalized the job/check-run
  summary projection, although the raw log preserved the recurring target-module failure marker.
- Linux evidence uses Debian bookworm CPython 3.13.15 in a disposable container with a read-only
  repository mount. Hypothesis used its documented in-memory fallback because its repository
  example database was unwritable.
- Independent review, human acceptance and merge remain pending.
