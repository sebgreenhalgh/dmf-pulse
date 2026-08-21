# LIVE-ODDS-001 implementation result

Status: **ENGINEERING COMPLETE PENDING INDEPENDENT REVIEW**.

The implementation is based on immutable parent
`baed47bce7a158d91afe38351a2c65be60444adf` on branch
`integration/post-gw1/LIVE-ODDS-001-production-live-odds`. No readiness merge, rebase,
bulk cherry-pick, PR, merge, tag, production activation, or human-acceptance action occurred.

## Implemented capability

- A first-class stdlib `http.client.HTTPSConnection` transport is the production default behind
  the later-main `OddsTransport` protocol. It fixes the approved TLS host/path, disables redirect
  following, applies connect/read/total budgets, bounds response reads to the configured maximum
  plus one detection byte, retains only allowlisted headers, hashes request IDs, and maps all lower
  failures to typed secret-free errors. `UrllibOddsTransport` remains explicit-only and is never a
  fallback.
- Credentials resolve lazily at the final runtime boundary from a systemd credential file or the
  named process environment fallback. Values are validated, excluded from request fingerprints,
  targets, representations, exception chains, persistence, and evidence. No real credential was
  read.
- The governed provider request is exactly EPL `soccer_epl`, region `uk`, markets `h2h,totals`,
  decimal odds, ISO time, request cost 2, with optional bounded commence filters.
- The provider-native current-input contract carries supported H2H/totals, receipt/cutoff/usable
  times, quota, conservative rights, transport/config provenance, source-body hash, quality, and a
  supported-market semantic hash. It performs no FPL identity mapping.
- Additive unsupported market keys are unique/sorted, recorded as
  `ADDITIVE_UNSUPPORTED_MARKET:<key>`, and excluded from accepted current markets. Their presence
  changes source provenance but not supported-market semantics. Missing/malformed mandatory H2H,
  invalid times, post-cutoff material, rights denial, and secret-like unexpected fields remain
  blocking. Optional totals retain explicit degradation.
- Parser reconciliation preserves later-main bounds and duplicate controls while making totals
  outcome identity line-aware. Unexpected secret-like provider fields retain their names for the
  blocker but have their values redacted before any parsed Pydantic representation can expose them.

## Verification summary

- Focused Odds/markets acceptance: 309 passed.
- Ticket coverage gate: 114 passed; 90.39% branch-aware combined coverage across the changed
  client, credential, and current-input modules; current-input module 95% in the focused report.
- Repository unit suite: 1,998 passed, 452 non-unit tests deselected; 77 inherited adversarial
  Pydantic warnings.
- Property suite: 88 passed, 23 deselected; contract suite: 72 passed, 68 deselected; non-database
  security suite: 27 passed, 6 deselected.
- Broader Odds/security attempt: 313 passed and four setup errors, all caused by absent
  `DMF_TEST_DATABASE_URL`; no behavioral failure.
- Frozen sync, repository-wide Ruff formatting/lint, strict mypy, secret scan, sdist/wheel build,
  and clean installed-wheel smoke passed. The canonical database-backed wheel verifier was
  environment-blocked by the same absent database URL.

Exact commands and outcomes are retained in `COMMAND_LEDGER.txt`; detailed limitations and
self-review closure are in `KNOWN_LIMITATIONS.md` and `FINAL_SELF_REVIEW.md`.
