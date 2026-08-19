# GW1 Checkpoint 1.3C Acceptance / Operator Contract

- Starting remote SHA — `8a678cb3f08ef0894a4468b6d37674f0e5a1b935`
- Operator-contract commit — `83e66db98807697819b5bf31228b515756688722`
- Workflow run — `32262150075`
- Overall — `PASS`
- Engineering path — `VALIDATED`
- Real provider call — `NOT EXECUTED`
- `REAL_CREDENTIALLED_PROVIDER_CALL = OPERATOR_CHECKPOINT`
- Acceptance/evidence commit SHA — pending exact-SHA attestation

## Results

- Focused CLI/current-input acceptance — `PASS`, `73 passed`
- Ruff format/lint — `PASS`
- Strict mypy — `NOT_EXECUTED` (no production Python changed)
- PostgreSQL integration — `NOT_EXECUTED` (accepted 1.3B evidence remains controlling)
- Wheel build and clean-environment install — `PASS`
- Installed package import, `credential-status`, and snapshot help — `PASS`
- Installed missing-credential path — `PASS`, exit `4`, no transport
- First-party secret scan — `PASS`, `finding_count=0`
- Git diff checks — `PASS`

## Installed missing-credential envelope

```json
{"bookmaker_observations_seen": 0, "current_input": null, "error": {"code": "CREDENTIAL_UNAVAILABLE", "message": "approved runtime credential is unavailable", "retryable": false, "transport_called": false}, "events_seen": 0, "market_observations_seen": 0, "outcomes_seen": 0, "provider": "the_odds_api", "quality": {"blockers": ["CREDENTIAL_UNAVAILABLE"], "status": "BLOCKING", "warnings": []}, "quota": null, "schema_version": "1.0.0", "source_snapshot_id": null, "status": "BLOCKED"}
```

## Contract boundary

- Provider configuration: `the_odds_api`, `soccer_epl`, `uk`, `h2h`, decimal, cost `1`, attempts `2`, timeouts `10/20/30` seconds.
- Output: `ODDS_PROVIDER_CURRENT_INPUT`, `PROVIDER_NATIVE_UNMAPPED`.
- Canonical FPL fixture mapping and fuzzy matching: not performed.
- Quota: configured and provider last-request cost `1`; live remaining/used was not observed because no real credentialled call was made.
- Rights/storage: private automated/transient/derived/internal use allowed; raw retention zero; public display, redistribution, backup and model training effectively denied.
- Temporal: fresh nonpast cutoff required; request, receipt, capture, cutoff, provider and usable timestamps preserved; no backdating.
- No Checkpoint 1.4 work was started.
