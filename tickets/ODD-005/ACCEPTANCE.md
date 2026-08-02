# ODD-005 Acceptance Contract

ODD-005 is accepted only when every mandatory outcome below is demonstrated from the exact baseline and final clean commit.

## A. Preflight and governance

1. Branch is `stage/A5/ODD-005-odds-provider-foundation`.
2. Baseline is exactly `7034e38f32cd579c90d35c5fe3f10921c3656be0`.
3. Initial and final trees are clean.
4. Pack manifest and detached hashes validate.
5. No live provider request occurs.
6. No real API key or payload enters repository, logs, tests, evidence or review ZIP.
7. Provider choice is The Odds API; API-FOOTBALL is not implemented.

## B. Mandatory FPL-004 remediation

1. Direct and `URLError`-wrapped TLS/certificate failures are typed `TLS_ERROR` and non-retryable.
2. TLS failures cause zero retry attempts beyond the failing call.
3. Source-bundle publication derives rights and quality from authoritative persisted records.
4. Bundle rights profile is relationally bound to member snapshots and profile version.
5. Missing, denied, unknown or mismatched bundle rights fail closed.
6. Open P0/P1 quality issues prevent bundle publication even if a caller supplies a favourable label.
7. Bundle code commit is recorded when available.
8. Array type fingerprints retain every observed heterogeneous type deterministically.
9. Alias `normalized_nfc` is real Unicode NFC.
10. Decimal semantic hashing has a documented, tested canonical policy: parse through `Decimal`, render fixed-point, strip insignificant trailing fractional zeros and a trailing decimal point, and never use exponent notation. Thus `"1.80"` and `"1.8"` share one semantic hash.
11. All inherited FPL-004 tests and public behavior remain green.

## C. Provider and transport

1. Provider config allowlists `api.the-odds-api.com`, API v4, `soccer_epl`, one region and `h2h`.
2. GET only; HTTPS/TLS verification enabled; redirects restricted.
3. API key is injected through a credential interface and never stored in config, URL evidence, logs or exceptions.
4. Query is deterministic and contains only approved parameters.
5. Live command with no credential returns typed `CREDENTIAL_UNAVAILABLE`, exit 4 and zero transport calls.
6. Fake transport exercises success, timeout, 429, 4xx, 5xx, TLS, content type, oversize and malformed body.
7. Retry is bounded and only transient failures retry.
8. Quota headers are captured and internally coherent.
9. Quota depletion prevents transport before the next call.

## D. Payload and semantic validation

1. Top-level response array and event/bookmaker/market/outcome structures are strictly parsed.
2. `sport_key` must be `soccer_epl` for this ticket.
3. Timestamps are timezone-aware UTC.
4. Decimal odds are parsed through `Decimal` and must be greater than 1. Public observation/query strings preserve approved source scale; `"1.80"` is valid, while `"1"`, `"1.0"`, `"1.00"`, leading-zero forms and all values below 1 are invalid.
5. `h2h` is mapped to canonical full-time 1X2 semantics.
6. HOME, DRAW and AWAY outcomes are explicit and mutually exclusive within one operator book.
7. Unknown additive fields produce drift warnings.
8. Missing required fields, wrong types, duplicate conflicting outcomes and invalid odds quarantine.
9. Unknown market keys are retained as typed unsupported evidence or quarantined; they never become 1X2.
10. Incomplete books are stored/flagged as incomplete but not normalised.
11. No raw implied probability, de-vigged probability or consensus is produced by Stage 5.

## E. Canonical mapping and persistence

1. Provider event ID maps to a canonical fixture only through an explicit mapping plan and season/competition context.
2. Home/away labels are validated against the mapped fixture but do not create identity.
3. Bookmaker key maps to one canonical betting operator through explicit provider-scoped mapping.
4. No bookmaker title or team name is used as the primary identity.
5. Market identity includes operator, fixture, definition, period, line and settlement profile.
6. Selection identity is market-scoped.
7. Source snapshot and quota metadata are immutable and source-linked.
8. Odds observations are append-only and exact Decimal values round-trip.
9. Repeated identical retrieval creates a new retrieval observation but no duplicate effect within one source snapshot.
10. A later changed quote appends rather than updates.
11. Unresolved fixture/operator mapping quarantines and prevents usable market publication.
12. Every canonical quote traces to a USABLE source snapshot and Rights Profile.

## F. As-of query

1. Query uses `usable_at <= as_of`, never provider time alone.
2. It returns the latest eligible observation per operator/market/selection under deterministic tie-breaking.
3. Post-cutoff quotes remain observed but do not appear in the earlier as-of result.
4. Corrections received later do not rewrite an earlier as-of result.
5. Complete, incomplete, suspended, unsupported and unavailable states are typed.
6. Result includes fixture, operator, market, selection, decimal odds, observed/source/received/usable times and lineage.

## G. Rights and retention

1. Machine-readable `synthetic_the_odds_api_v1` authorizes complete deterministic fixtures.
2. Machine-readable `the_odds_api_private_analytics_v1` reflects private analytical use, raw redistribution prohibition and conservative storage/training/publication limits.
3. Unknown rights deny.
4. Rights are checked before transport, raw write, canonical promotion, bundle publication, backup and export.
5. Raw-forbidden flow leaves no provider body on disk after success or failure.
6. Review ZIP contains no provider body marker or fake credential.
7. Standalone raw-data export is rejected.

## H. Database and migration

1. New Alembic revision is manually reviewed.
2. Clean base to head upgrade passes.
3. FPL-004 head `20260724_0002` to ODD-005 head passes.
4. Downgrade to FPL-004 head and re-upgrade pass.
5. Offline SQL contains no credentials.
6. PostgreSQL 18.4 only; no SQLite substitute.
7. Database constraints/triggers enforce market identity, quote validity, bundle rights/quality and immutability.
8. Concurrency tests cover duplicate retrieval, mapping and market publication.
9. Schema fingerprint is deterministic.

## I. Quality, package and security

1. Ruff/format and strict mypy pass.
2. Unit, property, contract, security, PostgreSQL integration and installed-wheel tests pass with zero skips.
3. Full inherited suite passes.
4. Overall branch coverage is at least 90%.
5. Critical odds ingestion, rights, quota, cutoff and FPL remediation branches meet at least 95% branch coverage.
6. Secret/canary scans report zero unapproved findings.
7. Installed wheel executes replay and query outside the source tree.

## J. Evidence and review archive

1. Every literal acceptance command is actually run and recorded.
2. Structured result says COMPLETE only with zero unresolved P0/P1 findings.
3. Review ZIP has at most 20 root files, no nested entries, valid CRC, manifest and detached hashes.
4. Review ZIP includes the complete human-authored patch from baseline.
5. Final commit, tests, coverage, migration head, payload SHA and archive SHA are recorded.

Any failed mandatory item yields BLOCKED or FAILED, not COMPLETE.
