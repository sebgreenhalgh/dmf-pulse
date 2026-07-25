# FPL-004 Acceptance Contract

FPL-004 is accepted only when every mandatory outcome below is demonstrated from a clean checkout at the exact baseline and final commit.

## A. Preflight and governance

1. Branch is `stage/A4/FPL-004-official-ingestion`.
2. Baseline is exactly `9b3160a2574d2868b5f26e3a2d429924567510b0`.
3. Initial and final trees are clean.
4. Pack manifest and all detached hashes validate.
5. Authority/decision references resolve.
6. No live FPL call occurs during implementation or acceptance.

## B. DAT-003 remediation

1. One immutable source snapshot represents one retrieval/import envelope.
2. Processing history is append-only and can progress after the snapshot is committed.
3. Interruption and resume work after store, parse, map and promotion.
4. `usable_at` is derived only after successful required stages.
5. Terminal quarantine/rejection cannot become usable.
6. Fixture season belongs to fixture competition.
7. Fixture and assigned Gameweek share a season.
8. Cross-season and cross-competition records are rejected by PostgreSQL, not only application code.
9. Schema hash excludes runtime-only PostgreSQL patch metadata.
10. Ruleset ID/version conflicts are database-rejected.
11. Data-quality records have an explicit subject/scope.

## C. Rights and raw retention

1. Rights Profile is versioned and machine-readable.
2. Default official FPL profile allows bounded transient manual validation but denies automated access.
3. Default profile denies persistent raw storage, persistent derived storage, source-bundle creation, backup, public display, redistribution and training.
4. Synthetic test profile permits deterministic fixture processing.
5. Live snapshot command performs zero transport calls under denied rights.
6. Forbidden raw payload leaves no body file after success or failure.
7. Allowed synthetic raw storage is durable before parsing.
8. Rights/profile/version are retained in snapshot lineage and in bundle lineage only for rights-approved synthetic/authorized inputs.
9. Unknown right is deny, never allow.

## D. Schema and validation

1. Happy bootstrap and fixtures parse successfully.
2. Unknown additive fields are accepted and reported.
3. Missing required field quarantines.
4. Wrong type quarantines.
5. Malformed JSON quarantines.
6. Oversized/deep payload fails safely.
7. Timestamps are UTC and ordered.
8. Integer price units and Decimal percentages are exact.
9. Provider IDs remain season/provider-scoped mappings.
10. No name-only identity merge exists.

## E. Canonical promotion

1. Under the synthetic authorized profile, competition, season, Gameweeks, teams, players and fixtures are created/reused correctly.
2. Player FPL-season catalogue identity is separate from football player identity.
3. Team/player/fixture/Gameweek observations are append-only and source-linked.
4. Same payload repeated creates new retrieval snapshots but no duplicate unchanged canonical effect.
5. Changed price/status/deadline/kickoff/assignment appends a new observation/revision.
6. Mapping conflict quarantines affected snapshot/bundle.
7. Post-cutoff snapshot remains observed but is not source-bundle eligible.
8. Every promoted record traces to a usable source snapshot.

## F. Source bundle and quality

1. Bundle requires both BOOTSTRAP and FIXTURES roles.
2. Every member is usable before cutoff.
3. Manifest order and SHA-256 are deterministic.
4. Quality report distinguishes warnings, blockers and typed missingness.
5. Invalid member prevents publishable/usable bundle.
6. Replaying identical inputs with same cutoff yields semantically identical bundle content apart from immutable retrieval IDs/timestamps explicitly excluded from the semantic hash.

## G. HTTP/client behavior

1. Requests are deterministic and endpoint-allowlisted.
2. URLs/headers/logs are sanitized.
3. Timeout, 429, 5xx, content-type mismatch and oversize are typed failures.
4. Retry policy is bounded and does not evade quotas.
5. Fake transport proves rights check occurs before request.
6. No authenticated endpoint or credential support is added.
7. Official-profile manual import may validate transiently but creates no persistent canonical observation or source bundle.

## H. Database/migrations

1. New Alembic revision is manually reviewed.
2. Clean base → head upgrade passes.
3. DAT-003 head → FPL-004 head upgrade passes.
4. FPL-004 head → DAT-003 head downgrade passes.
5. Re-upgrade passes.
6. Offline SQL renders without credentials.
7. PostgreSQL 18.4 real integration only; no SQLite substitute.
8. Concurrency tests cover processing-event order and idempotent mapping/promotion.
9. Schema manifest/fingerprint is deterministic.

## I. Quality, package and security

1. Ruff/format passes.
2. Strict mypy passes.
3. Unit, property, contract, integration, security and installed-wheel tests pass.
4. Existing accepted tests regress cleanly.
5. Critical ingestion/rights/cutoff branches meet repository coverage gates.
6. No secret, real payload, personal data or body text appears in logs/evidence/review archive.
7. Lock/SBOM/dependency evidence is current.
8. Installed wheel runs replay/import validation outside source tree.

## J. Evidence and review package

1. Every required acceptance command was actually run and recorded.
2. Structured result says COMPLETE only with zero unresolved P0/P1 findings.
3. Review ZIP has at most 20 root files, no nested entries, valid CRC and detached hashes.
4. Review ZIP includes the complete human-authored patch from baseline.
5. Final commit and ZIP SHA-256 are recorded.

Any failed mandatory item makes status BLOCKED or FAILED, not COMPLETE.
