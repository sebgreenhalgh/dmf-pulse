# LIVE-ODDS-001 independent-review finding disposition

Reviewed checkpoint: `6c36e73adef21b52ed54d23733e5a34c71547a6d`.

This file is append-only in meaning: reproduction and historical evidence are
not erased when a later checkpoint closes a finding. Commit fields are filled
with the checkpoint that contains the corresponding remediation.

## REV-001 — hard total deadline

- Original finding: stale read timeout survives request writing and an outer
  body read can return only after the total deadline.
- Reproduction: **REPRODUCED**. After 19 seconds of a 30-second total budget,
  `getresponse()` observed 20 seconds rather than the required 11 seconds. A
  deterministic body fake returned after 31 seconds before the client reported
  `TOTAL_TIMEOUT`.
- Root cause: remaining time was checked but not reapplied before response
  headers; `HTTPResponse.read()` may perform multiple underlying waits.
- Code fix: R3 uses one monotonic attempt boundary and recalculates the
  applicable `min(phase remaining, total remaining)` bound before each TCP
  address connect, TLS handshake, request write, response-header wait, and
  raw buffered receive. A deadline socket facade is installed before request
  writing; its raw reader reapplies the current total/read bound inside one
  outer `HTTPResponse.read()`. Retry request timeouts are derived from the
  original client deadline after elapsed transport time and retry delay.
- Tests: TD-01..12 plus direct request-write and TCP/TLS split-operation
  regressions pass. The R3 focused matrix passed 161 tests with 4 PostgreSQL
  cases deselected; `client.py` branch-aware coverage was 90.28%.
- Final status: **CLOSED**; final R5 focused and broader acceptance passed.
- Remediation commit: `a9f325763ae17d08f03c47cbd9bde3d5a2228182`.

## REV-002 — traceback-local secret/raw retention

- Original finding: escaping production traceback frames retain raw
  credentials, credential-bearing requests, raw response material, and
  pre-redaction provider fields.
- Reproduction: **REPRODUCED**. The `fetch` frame retained direct credential,
  request, attempt-request, refreshed-request, and response locals. Early
  parser text-limit failure retained the provider canary in
  `parse_odds_payload` and recursive `_check_text_limits` frames while ordinary
  exception rendering remained clean.
- Root cause: public raising frames also perform unsafe resolution/exchange or
  validate decoded raw structures before redaction.
- Code fix: R2 separates unsafe and safe scopes at parser, client, and both
  stdlib transport boundaries. Unsafe scopes catch every lower-level failure
  and return bounded sanitized state; only frames that have released the
  credential/request/raw body may raise. `OddsHttpRequest` no longer stores or
  exposes a credential. Secret-like provider values are irreversibly replaced
  before structured validation can raise.
- Tests: SEC-TB-01..19 recursively walk traceback, cause, context, production
  frame locals, mappings, sequences, object dictionaries, and slots across
  credential resolution, construction, transport, response, retry, parser,
  direct-transport, and request-retention cases. The R2 focused matrix passed
  162 tests with 5 PostgreSQL cases deselected.
- Final status: **CLOSED**; final R5 traceback/security acceptance passed.
- Remediation commit: `ac638e3ee6bbce8064a06e96102c2cfaa00be0d5`.

## REV-003 — production environment secret

- Original finding: the default runtime provider accepts the raw value of
  `DMF_PULSE_ODDS_API_KEY`.
- Reproduction: **REPRODUCED**. The injected process environment made both
  credential resolution and health report configured.
- Root cause: a raw-value process fallback followed the systemd credential
  path.
- Code fix: the production provider now resolves only
  `CREDENTIALS_DIRECTORY/<approved credential name>`; the environment may
  identify that non-secret directory but no raw API-key environment value is
  read. Injected mappings retain only the directory identifier.
- Tests: raw environment value ignored in resolution and health, systemd file
  success, invalid/bounded content, symlink, static test injection, and
  forbidden CLI/`.env` source coverage. The R2 focused matrix passed 162 tests
  with 5 PostgreSQL cases deselected.
- Final status: **CLOSED**; final R5 credential/security acceptance passed.
- Remediation commit: `ac638e3ee6bbce8064a06e96102c2cfaa00be0d5`.

## REV-004 — semantic hash polluted by acquisition state

- Original finding: `market_semantic_sha256` includes source snapshot and local
  receipt/usable/age fields.
- Reproduction: **REPRODUCED**. Identical body and accepted events with a
  distinct snapshot ID produced a different semantic hash; changing only local
  receipt/usable timing also changed it.
- Root cause: one hash payload mixed supported quote semantics with acquisition
  provenance.
- Code fix: R4 projects only supported provider-published market meaning:
  provider/contract/domain identity, provider event/participant/commence
  material, bookmaker identity, H2H/totals lines and prices, and provider
  update timestamps. It excludes source snapshot, response/body identity,
  request/receipt/capture/cutoff/usable times, age at receipt, quota, rights,
  quality warnings, and all other acquisition provenance. Provider timestamps
  remain semantic under the explicit DMFP-03/05/06 authority decision in the
  remediation plan.
- Tests: HASH-01..12 pass, including distinct-acquisition equality and an
  exact recursive payload-field audit. The former shallow PD-18 assertion now
  executes production `OddsPersistence.prepare()` and the actual consensus
  evaluator: totals plus an unsupported additive market yield exactly two H2H
  prepared books/six H2H observations and no unsupported fair-price material.
  The R4 downstream matrix passed 124 tests; `current.py` branch-aware coverage
  was 95.09%.
- Final status: **CLOSED**; final R5 Odds/markets acceptance passed.
- Remediation commit: `5475348b77b0be3fbd8766f4565721b98819d652`.

## REV-005 — false secret-scan evidence

- Original finding: sealed ledger claimed zero findings while independent
  review found eight.
- Reproduction: **REPRODUCED**, with an additional root cause. In the existing
  dedicated worktree, the exact scanner returned zero because the absolute
  path contains excluded component `review_pack`, causing every candidate to
  be skipped. In a clean clone outside that path, the exact command returned
  eight findings with the independently reported safe fingerprints.
- Root cause: two production/test-source finding classes plus a repository-root
  path exclusion defect that created the original false zero.
- Code fix: R2 removed both production-source findings and the request-contract
  test signal. R5 constructs the remaining five synthetic values at runtime,
  with no allowlist addition, and makes scanner exclusions relative to the
  scanned root so a parent directory named `review_pack` cannot skip the tree.
- Tests: the scanner-root regression and 62-test scanner/transport matrix
  pass. The exact final scanner command genuinely covered this worktree and
  returned exit 0, `PASS`, finding count 0.
- Final status: **CLOSED**.
- Remediation commit: R5 sealing commit containing this disposition and the
  scanner fix; exact pushed HEAD is recorded in `REMEDIATION_RESULT.md` handoff.
