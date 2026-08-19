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
| 1.4 FPL / odds identity integrity | COMPLETE | Exact team and target-GW fixture identity bridge accepted. |
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

- Validated commit — `6991e586c77301d6a0cc26246144f71c1cf49cb0`.
- Workflow run — `32281522483`.
- Validation result — `PASS`.
- Machine-written evidence — `evidence/readiness/GW1_SESSION1_VALIDATION_1_4A.md`.
- Mapping remains exact, reviewed, cutoff-bound and fail-closed; no fuzzy matching.
- Combined FPL-derived result remains transient/in-memory; PostgreSQL was not used.
- Real credentialled provider call — `OPERATOR_CHECKPOINT`.
- Checkpoint 1.5 — `NOT_STARTED`.
- Exact next action — **CHECKPOINT 1.4B — EXACT FIXTURE RESOLUTION / COVERAGE**.
<!-- GW1-1.4A-END -->

## Checkpoint 1.4B — verified recovery and local pre-publication validation

- Recovery starting remote SHA — `3e383927a4366e4cf0e26d2f9a6aaee0ccc005ed`.
- Accepted 1.4A evidence head restored as authority —
  `3abd02aa28959b0cfa6f56f3b5e58271ae0c9e61`.
- Decoded recovery archive SHA-256 —
  `ef8b77ed50a5317eb32ead4b1c219da78321049b8e52dc73d6a24fdbe8530ce7` (verified).
- Recovered mapping-contract Git blob —
  `e0a9f00248ac88c1f01893916e88345b14ddc36c` (verified as the archive's exact
  `src/dmf_pulse/ingestion/odds/mapping.py`).
- Temporary recovery archive and publisher workflow — removed.
- Formatted recovered source SHA-256 values — identity
  `3cc9783c070dee26ba282835e4a8aaeb07070b13104b0f9308d09a4d4928154c`, mapping
  `492ab91fda30a0c89fb2ce6b7603f26d7f3bada4d7cb74243631ec4c5c151977`, fixture tests
  `fba6551a8ee77f38a6676c36bab5f81a1f0c27ffca4da9be12edaba0871924d2`.
- Recovered identity tests — `51 passed`.
- Focused Linux-equivalent local suite — `157 passed, 1 deselected`; the deselected
  test requires Windows symlink privilege unavailable on this host and remains enabled
  for the Linux branch workflow.
- Ruff format/lint, strict mypy, wheel build, first-party secret scan and diff check —
  `PASS`.
- Repository validation — `FAIL` against the pre-existing stale branch-wide current
  manifest; this is not promoted to a Checkpoint-1.4 pass and must be remediated by final
  engineering acceptance.
- PostgreSQL — `NOT_EXECUTED` (transient/DB-free identity architecture).
- Real credentialled provider call — `OPERATOR_CHECKPOINT`.
- Exact next action — publish the required capability commit, verify remote equality, and
  consume the Linux focused-validation result before bounded Checkpoint 1.4C review.

<!-- GW1-1.4B-START -->
## Checkpoint 1.4B — automated focused publication

- Validated commit — `16560a1f8e50a7a6b33a6a7430f4ca9a01be30ff`.
- Workflow run — `32313356458`.
- Validation result — `PASS`.
- Machine-written evidence — `evidence/readiness/GW1_SESSION1_CHECKPOINT_1_4_ACCEPTANCE.md`.
- Mapping remains exact, reviewed, cutoff-bound and fail-closed; no fuzzy matching.
- Combined FPL-derived result remains transient/in-memory; PostgreSQL was not used.
- Real credentialled provider call — `OPERATOR_CHECKPOINT`.
- Checkpoint 1.5 — `NOT_STARTED`.
- Exact next action — **CHECKPOINT 1.5 — SESSION-1 ARTIFACTS / OPERATOR WORKFLOW**.
<!-- GW1-1.4B-END -->
## Checkpoint 1.4C — hostile identity acceptance

- Starting accepted 1.4B evidence head —
  `ff57c0c12b8ba9f7730bf5d703c808e2b6f7955a`.
- P0 findings — none.
- P1 findings — one: a caller could deserialize a rehashed `FPL_ODDS_IDENTITY_MAP`
  whose nested team/Gameweek identity, approval time, official deadline, or reviewed
  team correspondence contradicted the top-level context. The construction service was
  safe, but the public output model did not independently reject every such mutation.
- P1 remediation — independently revalidate nested official identity namespaces,
  products, IDs and season; exact reviewed provider-team correspondence; team and fixture
  approval cutoffs; decision cutoff; official deadline; target Gameweek; coverage counts;
  used-team closure; source-lineage hash; and semantic hash during deserialization.
- P2 findings — none.
- P3 findings — none recorded for the bounded identity bridge.
- Identity tests — `59 passed`.
- Focused Linux-equivalent local suite — `165 passed, 1 deselected`; the deselected
  symlink test remains enabled for Linux CI and cannot run without Windows symlink privilege.
- Identity-module branch-aware coverage — `92.08%` (`431` statements, `150` branches).
- Ruff format/lint, strict mypy, wheel build, first-party secret scan and diff check —
  `PASS`.
- PostgreSQL — `NOT_EXECUTED` (transient/DB-free identity architecture).
- Rights/storage — combined FPL-derived identity remains transient/in-memory;
  persistence and database access remain false; no raw provider payload is retained.
- Real credentialled provider call — `OPERATOR_CHECKPOINT`.
- Remediation commit — `16560a1f8e50a7a6b33a6a7430f4ca9a01be30ff`.
- Linux validation workflow — `32313356458` (`PASS`, `166 passed`).
- Validation evidence head — `5d48a1bcabe8e3c4960f5c906b0a1492799abfde`.
- Checkpoint 1.4 — `COMPLETE`.
- Exact next action — **CHECKPOINT 1.5 — SESSION-1 ARTIFACTS / OPERATOR WORKFLOW**.
