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
| 1.3 Live The Odds API input foundation | IN_PROGRESS | Checkpoint 1.3A is complete and remotely validated; Checkpoint 1.3B is the exact next action. |
| 1.4 FPL / odds identity integrity | INCOMPLETE | Not started. |
| 1.5 Session-1 artifacts / operator workflow | INCOMPLETE | Not started. |

## Checkpoint 1.3A — live credential / transport wiring

### Published commits and remote state

- Capability commit — `3ba91a5b106a70f18cda1d21d81c0143472a4bc7` (`feat(gw1): wire secret-safe live odds transport`).
- Focused validation workflow commit — `a318175ec82d39df7458d9dc003a5a54a481827a`.
- First validation evidence commit — `0c19357bd7e525ea4b7205f6768f941444772815`.
- First validation workflow run — `32191636148`.
- Scan-safe remediation commit — `f23396a6d254cf681da0816f739dc3dc4428cebb`.
- Passing validation evidence commit — `ffe97f623f65c533379c65372672ff037683ebbc`.
- Passing validation workflow run — `32192196539`.
- Latest pushed and verified remote SHA before this attestation — `ffe97f623f65c533379c65372672ff037683ebbc`.

### Capability proved

- `OddsIngestionService` defaults to the accepted `RuntimeOddsCredentialProvider`; the live path does not instantiate a test-only provider.
- The accepted client resolves the runtime value lazily after the local quota gate and passes a valid dummy value only to the final transport object.
- The approved request is HTTPS-only and fixed to `api.the-odds-api.com` plus `/v4/sports/soccer_epl/odds`.
- Sanitized targets, request fingerprints, representations, fetch evidence and errors contain no credential value.
- Same-host, cross-host, HTTP-downgrade and repeated-chain-shaped redirects fail closed after one transport call.
- Existing ODD-005 client, parser, quota, rights and persistence infrastructure is reused; no parallel provider stack was introduced.

### First remote validation

- Focused pytest — PASS, `11 passed in 1.98s`.
- Ruff format — PASS.
- Ruff lint — PASS.
- Strict mypy on affected existing production modules — PASS.
- `git diff --check` — PASS.
- First-party secret scan — FAIL because the synthetic test constant name matched the repository scanner's sensitive-assignment heuristic; no real credential was present.

### Passing repeat validation and attestation

- Focused pytest — PASS, `11 passed in 2.08s`.
- Ruff format — PASS.
- Ruff lint — PASS.
- Strict mypy on `src/dmf_pulse/ingestion/odds/client.py` and `service.py` — PASS.
- `git diff --check` — PASS.
- First-party secret scan — PASS, `finding_count=0`.
- The validated commit was `f23396a6d254cf681da0816f739dc3dc4428cebb`; machine-written evidence is committed at `ffe97f623f65c533379c65372672ff037683ebbc`.
- Checkpoint 1.3A status — `COMPLETE`.
- Publication state — all 1.3A changes and evidence are pushed; remote ref equals the latest verified commit above.

## Rights and storage state

- Automated access, transient processing, derived storage and private internal use — declared/effective `ALLOW`.
- Raw storage — declared `UNKNOWN`, effective `DENY`; retention `0` seconds; raw payload is not retained.
- Public display and redistribution — declared/effective `DENY`.
- Backup and model training — declared `UNKNOWN`, effective `DENY`.

## Secret state

- Tests use synthetic placeholders only.
- No Sebastian credential was requested, stored, logged, committed or used.
- No credential-bearing URL or raw live provider payload is committed.
- `REAL_CREDENTIALLED_PROVIDER_CALL = OPERATOR_CHECKPOINT`.

## Known limitations and exact next action

- PostgreSQL-backed provider-native current-input evidence is not part of 1.3A and remains for 1.3B validation.
- No real credentialled provider call has occurred.
- Checkpoint 1.4 cross-provider identity mapping has not been started.
- Exact next action: **CHECKPOINT 1.3B — QUOTA / RETRIES / PROVIDER VALIDATION**.
