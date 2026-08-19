# GW1 2026/27 Readiness — Session 1 Live Input Foundation

## Immutable context

- Original immutable GW1 parent — `9eb57143f6ee92f67c78607cc386678d962e62d4`
- Canonical working branch — `readiness/GW1-2026-27-live-input-initial-squad`
- Checkpoint 1.3 session starting remote SHA — `4b813ff411908de9c1f35ae19494b619ed1391b5`
- Verified merge base — `9eb57143f6ee92f67c78607cc386678d962e62d4`
- Checkpoint 1.1 implementation commit — `448749c072900642a922ae1456d0d30111a3e9ea`
- Checkpoint 1.2 capability commit — `d8e95a442d24d0547a2b7a5fb585da94f66dcfe4`
- Checkpoint 1.2 evidence commit — `36a5c755330d5d7eeb465cbfa0e21b70cc0bf777`
- Checkpoint 1.2 publication-reconciliation commit — `4b813ff411908de9c1f35ae19494b619ed1391b5`

## Checkpoint status

| Checkpoint | Status | Durable evidence |
|---|---|---|
| 1.0 Remote state / progress bootstrap | COMPLETE | Immutable-parent ancestry and branch head verified. |
| 1.1 Runtime odds credential foundation | COMPLETE | Existing accepted implementation preserved unchanged. |
| 1.2 Current official FPL input foundation | COMPLETE | Existing accepted implementation preserved unchanged. |
| 1.3 Live The Odds API input foundation | COMPLETE | 1.3A, 1.3B and 1.3C are COMPLETE; operator contract and acceptance evidence are published. |
| 1.4 FPL / odds identity integrity | IN_PROGRESS | 1.4A published; focused validation failed and requires remediation. |
| 1.5 Session-1 artifacts / operator workflow | INCOMPLETE | Not started. |

## Checkpoint 1.3A — live credential / transport wiring

- Capability commit — `3ba91a5b106a70f18cda1d21d81c0143472a4bc7`.
- Passing validation evidence commit — `ffe97f623f65c533379c65372672ff037683ebbc`.
- Passing validation workflow run — `32192196539`.
- Exact 1.3A attestation commit and verified remote SHA — `1ade756c64df96c2ceb435a3d52c6ee5d96ea3b6`.
- Focused pytest — PASS, `11 passed in 2.08s`.
- Ruff format/lint — PASS.
- Strict mypy — PASS.
- First-party secret scan — PASS, `finding_count=0`.
- Checkpoint 1.3A status — `COMPLETE`.

## Checkpoint 1.3B — quota / retries / provider validation

### Starting state

- Exact 1.3B starting remote SHA — `1ade756c64df96c2ceb435a3d52c6ee5d96ea3b6`.
- Remote equality was verified before 1.3B work began.
- Existing `OddsClient`, parser, provider configuration, rights profile, quota ledger, source-envelope persistence and CLI command surface remain authoritative.
- No second provider client, parser, quota ledger or raw-payload persistence mechanism is introduced.

### Capability staged in the commit containing this update

- Add `ODDS_PROVIDER_CURRENT_INPUT`, a strict provider-native and explicitly unmapped EPL `h2h` output contract.
- Route the existing `dmf ingest odds snapshot` command through a thin live-current orchestration boundary that reuses the accepted ODD-005 client, parser, rights, quota and persistence components.
- Preserve provider event IDs, provider team text, kickoff times, bookmaker/market timestamps, outcome names, decimal prices, receipt/capture/cutoff/usable timestamps, quota state, configuration hashes, rights decisions and secret-free request provenance.
- Keep `canonical_fpl_fixture_mapping_performed=false`; no FPL fixture ID, canonical team ID or fuzzy mapping is created.
- Fail closed on empty provider responses, malformed JSON, duplicate JSON keys/outcomes, unsupported market/sport configuration, missing books or `h2h`, incomplete three-way outcomes, line-bearing outcomes, non-current events, impossible provider timestamps, unsafe request provenance and post-cutoff usability.
- Preserve bounded HTTP/retry behavior from the accepted client and report explicit 4xx, 429 and 5xx categories even when quota headers are absent; missing quota evidence remains conservative and cannot create an unbounded retry.
- Preserve provider quota remaining/used/last-cost evidence and verify the configured request cost.
- Record provider-native `USABLE` lifecycle evidence without creating canonical FPL mappings or market observations.
- Persist explicit deny decisions for public display, redistribution, backup and model training in addition to the existing automated/transient/raw/derived/private decisions.
- Retain no raw provider payload; only governed hashes, byte counts, quota state, timestamps and lifecycle evidence are stored.

### Tests staged

- 49 focused provider-native harness cases pass locally against reconstructed accepted interfaces.
- New unit coverage includes credential states, quota preflight, 200/401/403/429/5xx, malformed quota, bounded retry, timeout/TLS classes, redirect policy, size/content type, valid EPL `h2h`, parser/quality failures, temporal cutoff, rights and secret-free output.
- New CLI coverage proves no API-key option, provider-native JSON success, exact cutoff/database reference forwarding and secret-free failure output.
- New PostgreSQL integration coverage proves `FORBIDDEN` raw storage, no raw blob/object, quota and rights audit rows, `USABLE` lifecycle, and zero canonical market/odds rows.
- A branch-scoped workflow will run focused tests, inherited odds/CLI regressions, PostgreSQL migration plus integration, Ruff format/lint, strict mypy, wheel build, diff check and first-party secret scan, then commit machine-written evidence.

### Rights and storage state

- Automated access, transient processing, derived storage and private internal use — declared/effective `ALLOW`.
- Raw storage — declared `UNKNOWN`, effective `DENY`; retention `0` seconds; raw payload is not retained.
- Public display and redistribution — declared/effective `DENY`.
- Backup and model training — declared `UNKNOWN`, effective `DENY`.
- Current output is private analytical provider-native evidence only.

### Secret state

- Tests use synthetic placeholders only.
- No Sebastian credential was requested, stored, logged, committed or used.
- No credential-bearing URL or raw live provider payload is committed.
- `REAL_CREDENTIALLED_PROVIDER_CALL = OPERATOR_CHECKPOINT`.

### Known limitations and exact next action

- Provider-native bookmaker age is preserved, but no new staleness threshold is invented because the accepted provider configuration does not govern one.
- No real credentialled provider call has occurred.
- Checkpoint 1.4 cross-provider identity mapping has not been started.
- 1.3B remains `IN_PROGRESS` until the branch workflow passes, its evidence commit is verified, and an exact-SHA progress attestation is pushed.
- Exact next action after 1.3B validation and attestation: **CHECKPOINT 1.3C — CHECKPOINT ACCEPTANCE / OPERATOR CONTRACT**.

## Checkpoint 1.3B automated publication

- Workflow run — `32194395276`.
- Validation result — `FAIL`.
- Machine-written details — `evidence/readiness/GW1_SESSION1_VALIDATION_1_3B.md`.
- Real credentialled provider call — `OPERATOR_CHECKPOINT`.


## Checkpoint 1.3B remediation — 2026-08-19

- Exact remediation startup remote SHA — `196224c729e1df25a30f3a0d5ac55bac74f7fcc2`.
- Reproduced published workflow run — `32194395276` (`FAIL`).
- CLI root cause — the test asserted only `error`; the accepted public envelope also requires `schema_version` and `status`.
- PostgreSQL root cause — the provider-native path skipped the legal `MAPPED` and `PROMOTED` lifecycle stages before `QUALITY_PASSED`.
- Ruff root causes — one unsorted import block and one `Callable` import from `typing`.
- Remediation — preserve the production error envelope, restore the accepted lifecycle vocabulary with explicit provider-native/no-canonical-mapping semantics, strengthen ordered lifecycle coverage, and apply normal Ruff fixes.
- Remediation validation workflow — `32246327083`.
- Validation status before publication — `FAIL`.
- Remediation commit SHA — `e0e1459f203bd4f7e00c7173e18446b5e454cff7`.
- `REAL_CREDENTIALLED_PROVIDER_CALL = OPERATOR_CHECKPOINT`.
- No Checkpoint 1.3C or 1.4 implementation was started.
- Exact next action after a clean durable pass — **CHECKPOINT 1.3C — CHECKPOINT ACCEPTANCE / OPERATOR CONTRACT**.

### Remediation validation publication

- Workflow run — `32246327083`.
- Focused validation — `FAIL`.
- Validation/evidence commit SHA — `4ece4f1054e400720693ab223b4f8ddc0ac4cefc`.


## Checkpoint 1.3B immutable-snapshot remediation — run 32247073642

- Exact startup remote SHA — `7df6483a461e4cf2917c70b27aa52d75cac39822`.
- Prior remediation run — `32246327083` (`FAIL`).
- Remaining root cause — the live path attempted to update immutable `provenance.source_snapshot` fields after receipt; the append-only lifecycle already carries parsed/validated/mapped/promoted/quality/usable state.
- Resolution — remove the prohibited snapshot mutation, retain the immutable receipt envelope, and assert final state through the ordered processing-event ledger and `source_snapshot_lifecycle` view.
- Workflow run — `32247073642`.
- Validation — `PASS`.
- Focused provider/CLI tests — `64 passed`.
- Inherited odds tests — `103 passed`.
- Affected CLI tests — `29 passed`.
- PostgreSQL integration tests — `1 passed`.
- Ruff format/lint, strict mypy, wheel build, diff check and first-party secret scan — `PASS`.
- Code/remediation commit SHA — `03b76f08bb1648359e1c63a3c1d4ae4ea5d58f79`.
- `REAL_CREDENTIALLED_PROVIDER_CALL = OPERATOR_CHECKPOINT`.
- Raw provider payload retention remains forbidden; canonical FPL fixture/team mapping and fuzzy matching remain unperformed.
- Public display, redistribution, backup and model training remain denied.
- Checkpoint 1.3C and Checkpoint 1.4 were not started.
- Exact next action after a clean durable pass — **CHECKPOINT 1.3C — CHECKPOINT ACCEPTANCE / OPERATOR CONTRACT**.

### Current checkpoint matrix after the clean 1.3B pass

| Checkpoint | Status |
|---|---|
| 1.0 | COMPLETE |
| 1.1 | COMPLETE |
| 1.2 | COMPLETE |
| 1.3A | COMPLETE |
| 1.3B | COMPLETE |
| 1.3C | COMPLETE |
| 1.4 | INCOMPLETE / NOT_STARTED |
| 1.5 | INCOMPLETE / NOT_STARTED |

- Exact next action — **CHECKPOINT 1.3C — CHECKPOINT ACCEPTANCE / OPERATOR CONTRACT**.

### Final 1.3B validation publication

- Workflow run — `32247073642`.
- Validation result — `PASS`.
- Validation/evidence commit SHA — `d2ca5c934124c6ac6dab7391b35cf0d3fd3495e4`.


## Checkpoint 1.3C — acceptance / operator contract

- Starting remote SHA — `8a678cb3f08ef0894a4468b6d37674f0e5a1b935`.
- Operator-contract commit — `83e66db98807697819b5bf31228b515756688722`.
- Acceptance workflow — `32262150075` (`PASS`).
- Focused acceptance — `PASS`, `73 passed`.
- Ruff format/lint, wheel build/install, installed CLI credential status/help, controlled missing-credential path, diff check and first-party secret scan — `PASS`.
- Strict mypy — `NOT_EXECUTED`; no production Python changed.
- PostgreSQL integration — `NOT_EXECUTED`; accepted Checkpoint 1.3B database evidence remains controlling.
- Acceptance/evidence commit SHA — `a2f823ab53cec944e8bb7065d40b4950f7d11c9b`.
- Output — `ODDS_PROVIDER_CURRENT_INPUT`, `PROVIDER_NATIVE_UNMAPPED`, no canonical FPL mapping, no raw payload retention.
- Rights/storage and temporal contracts — unchanged and accepted.
- `REAL_CREDENTIALLED_PROVIDER_CALL = OPERATOR_CHECKPOINT`.
- Checkpoint 1.4 — `NOT_STARTED`.
- Exact next action — **CHECKPOINT 1.4 — FPL / ODDS IDENTITY INTEGRITY**.

<!-- GW1-1.4A-START -->
## Checkpoint 1.4A — automated focused publication

- Validated commit — `99f3e93ca769ca36639774af88135c734d4312c1`.
- Workflow run — `32280118079`.
- Validation result — `FAIL`.
- Machine-written evidence — `evidence/readiness/GW1_SESSION1_VALIDATION_1_4A.md`.
- Mapping remains exact, reviewed, cutoff-bound and fail-closed; no fuzzy matching.
- Combined FPL-derived result remains transient/in-memory; PostgreSQL was not used.
- Real credentialled provider call — `OPERATOR_CHECKPOINT`.
- Checkpoint 1.5 — `NOT_STARTED`.
- Exact next action — **REMEDIATE CHECKPOINT 1.4A VALIDATION**.
<!-- GW1-1.4A-END -->
