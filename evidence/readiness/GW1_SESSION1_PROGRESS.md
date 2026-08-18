# GW1 2026/27 Readiness — Session 1 Live Input Foundation

## Immutable context

- Original immutable GW1 parent: `9eb57143f6ee92f67c78607cc386678d962e62d4`
- Working branch: `readiness/GW1-2026-27-live-input-initial-squad`
- Starting remote SHA for this resumed Pro execution: `dc12ab2ef5bd576307a4e685770b2e9cfbce371c`
- Remote SHA immediately before the Checkpoint-1.1 attestation publication: `a6097b198852418156bd6f8d9698618970a023a4`
- Exact downloaded recovery workflow run ID: `32152205877`
- Exact downloaded recovery artifact ID: `9330181632`
- Checkpoint-1.1 capability commit: `448749c072900642a922ae1456d0d30111a3e9ea`

## Checkpoint status

| Checkpoint | Status | Durable evidence |
|---|---|---|
| 1.0 Remote state / progress bootstrap | COMPLETE | Immutable-parent ancestry verified; the downloaded recovery bundle and remote branch both resolve to the recorded starting SHA. |
| 1.1 Runtime odds credential foundation | COMPLETE | Runtime-only credential resolution, fail-closed validation, redaction, non-disclosing diagnostics, CLI/service wiring and focused tests verified on the recovered branch. |
| 1.2 Current official FPL input foundation | INCOMPLETE | Not yet implemented in this resumed execution. |
| 1.3 Live The Odds API input foundation | INCOMPLETE | Not started. |
| 1.4 FPL / odds identity integrity | INCOMPLETE | Not started. |
| 1.5 Session-1 artifacts / operator workflow | INCOMPLETE | Not started. |

## Remote and recovery verification

- The branch merge base with the immutable parent is exactly `9eb57143f6ee92f67c78607cc386678d962e62d4`.
- `BUNDLE_HEAD.txt` and `REMOTE_HEAD.txt` in the downloaded recovery artifact both contain `dc12ab2ef5bd576307a4e685770b2e9cfbce371c`.
- The recovered worktree was clean before the attestation correction.
- Direct Git HTTPS remains unavailable from the execution container; GitHub-connected inspection and downloaded workflow artifacts are the remote truth boundary for this resumed execution.
- A failed, temporary verification trigger and a corrupt staged publication workflow were removed; neither represented product capability.

## Checkpoint 1.1 evidence

- Relevant implementation files: `src/dmf_pulse/ingestion/odds/credentials.py`, `src/dmf_pulse/ingestion/odds/client.py`, `src/dmf_pulse/ingestion/odds/service.py`, `src/dmf_pulse/cli/odds_cmd.py`, and their focused tests.
- Runtime source identifiers: `CREDENTIALS_DIRECTORY/the_odds_api_key` (preferred) and process-scoped `DMF_PULSE_ODDS_API_KEY` fallback.
- No API-key CLI option exists.
- Diagnostic: `dmf ingest odds credential-status --output json`; output contains one boolean field only.
- The secret is resolved lazily at the final transport boundary and is not held in ordinary application configuration.
- Missing, malformed or unreadable credentials fail closed with `CREDENTIAL_UNAVAILABLE` and a non-disclosing message.
- Focused verification command covered runtime credentials, credential-status CLI, odds foundation, model/config, persistence/publication/transport boundaries, retry policy, non-PostgreSQL security, public contracts and affected CLI tests.
- Focused verification result: `193 passed, 4 deselected in 4.27s` with `-m "not postgres"`.
- PostgreSQL-only credential/quota-retention tests: `RESOURCE_LIMIT` because `DMF_TEST_DATABASE_URL` is unavailable; this is not a product failure.
- Ruff format on affected files: `PASS`.
- Ruff lint on affected files: `PASS`.
- Strict mypy on the four affected production modules: `PASS`.
- Actual provider call: `NOT_EXECUTED`; Sebastian's key remains an operator-only runtime input.

## Known blockers and limitations

- Sebastian's actual The Odds API key is intentionally unavailable and must never be pasted into ChatGPT or committed.
- A real credentialled provider call remains an `OPERATOR_CHECKPOINT`.
- Automated official-FPL transport remains denied by the current rights profile. Checkpoint 1.2 must use a manual-capture, transient-processing, no-raw-storage route and must not claim broader rights.
- No projection, player-points integration, Stage-10 optimiser integration, initial-squad recommendation, Stage-12 prospective logging, captaincy, chip work, PR, merge or production activation is in scope.

## Restart handoff

- Exact next action: implement Checkpoint 1.2A, the current official-FPL contracts, parsing and canonical validation, then test and publish it before beginning the governed service path.
