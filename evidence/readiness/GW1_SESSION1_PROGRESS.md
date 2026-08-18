# GW1 2026/27 Readiness — Session 1 Live Input Foundation

## Immutable context

- Original immutable GW1 parent — `9eb57143f6ee92f67c78607cc386678d962e62d4`
- Canonical working branch — `readiness/GW1-2026-27-live-input-initial-squad`
- Checkpoint 1.3 session starting remote SHA — `4b813ff411908de9c1f35ae19494b619ed1391b5`
- Checkpoint 1.1 implementation commit — `448749c072900642a922ae1456d0d30111a3e9ea`
- Checkpoint 1.2 capability commit — `d8e95a442d24d0547a2b7a5fb585da94f66dcfe4`
- Checkpoint 1.2 evidence commit — `36a5c755330d5d7eeb465cbfa0e21b70cc0bf777`
- Checkpoint 1.2 publication-reconciliation commit — `4b813ff411908de9c1f35ae19494b619ed1391b5`

## Checkpoint status

| Checkpoint | Status | Durable evidence |
|---|---|---|
| 1.0 Remote state / progress bootstrap | COMPLETE | Immutable-parent ancestry and recovery-bundle continuity verified. |
| 1.1 Runtime odds credential foundation | COMPLETE | Existing accepted implementation preserved unchanged. |
| 1.2 Current official FPL input foundation | COMPLETE | Governed manual/transient official-FPL current-input capability is published. |
| 1.3 Live The Odds API input foundation | IN_PROGRESS | Subcheckpoint 1.3A implementation is staged in the commit containing this progress update; remote validation and exact-SHA attestation remain required. |
| 1.4 FPL / odds identity integrity | INCOMPLETE | Not started. |
| 1.5 Session-1 artifacts / operator workflow | INCOMPLETE | Not started. |

## Checkpoint 1.3A — live credential / transport wiring

### Starting state

- Exact starting remote SHA — `4b813ff411908de9c1f35ae19494b619ed1391b5`.
- Merge base with the immutable GW1 parent — `9eb57143f6ee92f67c78607cc386678d962e62d4`.
- Repository inspection confirmed Checkpoints 1.1 and 1.2 complete and Checkpoint 1.3 next.
- Existing ODD-005 client/parser/quota/rights/persistence infrastructure is reused; no parallel provider client, parser or persistence stack is introduced.

### Capability proved in this implementation commit

- The accepted runtime `DMF_PULSE_ODDS_API_KEY` provider remains the default on `OddsIngestionService`; no alternate or test-only provider is instantiated by the live service.
- Focused tests prove the existing service-to-client-to-transport wiring resolves credentials lazily and passes a valid dummy value only at the final transport boundary.
- Focused tests prove local quota refusal precedes credential resolution and transport construction.
- Focused tests prove the accepted request remains locked to the configured HTTPS host/path and that credential material is absent from sanitized targets, fingerprints, representations and returned fetch evidence.
- Focused tests prove every redirect response is terminal on the first transport call, including same-host, cross-host, HTTP-downgrade and repeated-chain-shaped locations.
- Existing ODD-005 transport, parser, quota, rights and persistence infrastructure is reused unchanged; no parallel provider stack is introduced.
- Provider-native output, response-quality hardening and operator acceptance remain explicitly deferred to 1.3B/1.3C.

### Focused tests added

- Default live service uses `RuntimeOddsCredentialProvider`.
- Valid dummy runtime credential reaches only the final transport boundary.
- Missing, blank and malformed credentials return controlled `CREDENTIAL_UNAVAILABLE` without transport.
- Local quota exhaustion blocks before credential resolution or transport.
- Same-host, cross-host, HTTP-downgrade and repeated-chain-shaped redirects fail closed after one call.
- Credential material is absent from errors, fetch evidence, request representations, sanitized targets and request fingerprints.

### Validation before publication

- Python compilation of the new focused test module — PASS.
- Full repository pytest / Ruff / strict mypy — pending remote branch validation because this execution environment does not contain an authenticated full checkout or a locally cached Ruff binary.
- `REAL_CREDENTIALLED_PROVIDER_CALL = OPERATOR_CHECKPOINT`.

### Rights and storage state

- Automated access, transient processing, derived storage and private internal use must be declared and effectively allowed.
- Raw storage is declared `UNKNOWN`, effective `DENY`; raw retention is `0` seconds and `raw_payload_retained=false`.
- Public display and redistribution are declared/effective `DENY`.
- Backup and model training are declared `UNKNOWN`, effective `DENY`.

### Secret state

- Tests use the dummy value `dummy-odds-key-1234567890` only.
- No real Sebastian credential is requested, stored, logged, committed or used.
- No credential-bearing URL or raw live provider payload is committed.

### Known limitations and next action

- No real credentialled provider call has occurred.
- PostgreSQL-backed evidence recording has not yet been validated in this subcheckpoint publication.
- Checkpoint 1.4 cross-provider identity mapping has not been started.
- Exact next action after remote validation and exact-SHA attestation: **CHECKPOINT 1.3B — QUOTA / RETRIES / PROVIDER VALIDATION**.
