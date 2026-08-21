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
- Code fix: pending R3.
- Tests: TD-01 RED in R1; complete TD matrix pending R3.
- Final status: **OPEN**.
- Remediation commit: pending.

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
- Code fix: pending R2.
- Tests: property-level production traceback walker RED in R1; complete
  SEC-TB matrix pending R2.
- Final status: **OPEN**.
- Remediation commit: pending.

## REV-003 — production environment secret

- Original finding: the default runtime provider accepts the raw value of
  `DMF_PULSE_ODDS_API_KEY`.
- Reproduction: **REPRODUCED**. The injected process environment made both
  credential resolution and health report configured.
- Root cause: a raw-value process fallback followed the systemd credential
  path.
- Code fix: pending R2; systemd credential file only, with explicit test
  injection remaining separate.
- Tests: CRED-02/CRED-03 RED in R1; complete credential matrix pending R2.
- Final status: **OPEN**.
- Remediation commit: pending.

## REV-004 — semantic hash polluted by acquisition state

- Original finding: `market_semantic_sha256` includes source snapshot and local
  receipt/usable/age fields.
- Reproduction: **REPRODUCED**. Identical body and accepted events with a
  distinct snapshot ID produced a different semantic hash; changing only local
  receipt/usable timing also changed it.
- Root cause: one hash payload mixed supported quote semantics with acquisition
  provenance.
- Code fix: pending R4. Provider-published quote/event timestamps remain
  semantic under DMFP-03/05/06; local acquisition fields do not.
- Tests: HASH-01/HASH-02 RED in R1; full HASH-01..12 matrix pending R4.
- Final status: **OPEN**.
- Remediation commit: pending.

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
- Code fix: pending R2/R5. Production findings will be fixed, test canaries
  constructed safely or exactly allowlisted only if necessary, and scanner
  coverage will be validated outside the excluded parent.
- Tests: scanner-root regression RED in R1.
- Final status: **OPEN**.
- Remediation commit: pending.
