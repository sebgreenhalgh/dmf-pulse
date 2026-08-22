# LIVE-ODDS-001 known limitations

## Original GW1 failure

**ROOT CAUSE NOT FULLY ESTABLISHED.**

Successful emergency `http.client` reachability was observed during GW1, but the precise original
urllib `SOURCE_UNAVAILABLE` cause was not reproduced or isolated in this offline implementation
session. The emergency patch itself was not promoted. The production result is a governed transport
behind the existing protocol with explicit TLS, timeout, response-bound, redirect, retry, quota,
provenance, and secret-handling contracts.

## Verification boundaries

- Acceptance used only repository fixtures and deterministic fake connections. No real provider
  request was made and no local/runtime API key was read, so live account reachability and current
  provider quota state remain operational deployment checks.
- Four PostgreSQL security tests and the canonical database-backed wheel verifier could not run
  because `DMF_TEST_DATABASE_URL` was not supplied. They are recorded as
  `ENVIRONMENT_BLOCKED`, not passed. All 309 non-database focused Odds/markets tests passed.
- The available execution platform was Windows. The transport and credential tests assert no
  platform branches or filesystem assumptions in the transport, and systemd/process credential
  behavior is covered with portable filesystem fakes, but a native POSIX run remains for CI or the
  independent reviewer.
- Python's synchronous OS resolver has no portable stdlib cancellation primitive. Resolution runs
  before the application-controlled TCP primitive; after resolution, the transport recalculates
  and enforces the connect/total bound separately for each TCP address and TLS handshake, then the
  read/total bound for every write/header/receive primitive. No background worker, subprocess,
  alternate transport, or silent timeout fallback was introduced to disguise that platform
  resolver boundary.
- This unit stops at provider-native unmapped current Odds input. FPL/team/fixture identity
  reconciliation, live snapshot composition, orchestration, and Stage-6 algorithm changes remain
  deliberately excluded.

Independent review, human acceptance, PR creation, merge, and production promotion remain pending.
