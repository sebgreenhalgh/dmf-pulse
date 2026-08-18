# GW1 2026/27 Readiness — Session 1 Live Input Foundation

## Immutable context

- Original immutable GW1 parent: `9eb57143f6ee92f67c78607cc386678d962e62d4`
- Working branch: `readiness/GW1-2026-27-live-input-initial-squad`
- Starting remote SHA for this Pro execution — `13086c8892d4e47967a9485262ab647c088ad1cf`
- Recovery workflow trigger SHA: `2da7291f8f8d27e2857d9ea548a866d281f79cd9`
- Recovery workflow run ID: `32139990719`
- Latest pushed SHA: recorded in the recovery bundle as `BUNDLE_HEAD.txt`; refreshed after each capability checkpoint.

## Checkpoint status

| Checkpoint | Status | Durable evidence |
|---|---|---|
| 1.0 Remote state / progress bootstrap | COMPLETE | Branch ancestry verified; source, dependency and tool recovery artifacts verified; this record published on the working branch. |
| 1.1 Runtime odds credential foundation | COMPLETE | Runtime provider supports systemd credential files and a process-scoped PowerShell fallback; malformed/blank/absent secrets fail closed; boolean-only diagnostic and focused tests added. |
| 1.2 Current official FPL input foundation | INCOMPLETE | Not yet implemented. |
| 1.3 Live The Odds API input foundation | INCOMPLETE | Not yet implemented. |
| 1.4 FPL / odds identity integrity | INCOMPLETE | Not yet implemented. |
| 1.5 Session-1 artifacts / operator workflow | INCOMPLETE | Not yet implemented. |

## Existing branch state inspected

- The branch is descended from the immutable parent and already contains recoverability-only bootstrap commits and artifacts.
- No Session-1 credential, current-input, live-odds, identity-mapping or operator-workflow capability was found in the recovered source snapshot.
- No prior Session-1 progress record was present.
- Existing accepted FPL and odds ingestion foundations remain in place and will be extended rather than replaced.
- Redundant bootstrap source archives/chunks were removed from the live tree after exact bundle recovery because they defeated bounded repository secret scanning; their commits remain in immutable Git history.

## Validation performed for checkpoint 1.0

- Immutable-parent ancestry: PASS.
- Remote branch discovery: PASS.
- Recoverable source archive checksum and extraction: PASS.
- Offline dependency archive checksum and extraction: PASS.
- Offline Ruff binary checksum and execution: PASS.
- Direct Git HTTPS from the execution container: RESOURCE_LIMIT (outbound DNS/network unavailable).
- GitHub-connected publication and branch inspection: PASS.

## Known blockers and limitations

- Sebastian's actual The Odds API key is intentionally unavailable and must never be pasted into ChatGPT or committed.
- A real credentialled provider call remains an OPERATOR CHECKPOINT.
- Automated official-FPL transport remains subject to the existing rights profile; Session 1 must preserve the compliant transient/manual path unless governance changes independently.
- No projection, optimiser, squad recommendation, captaincy, prospective logging or later-stage work is in scope.

## Restart handoff

- Worktree clean at checkpoint publication: verified by the recovery workflow before push.
- Local/remote equality: verified by the recovery workflow after push and captured in the recovery bundle.
- Exact next action: implement checkpoint 1.2, the governed current official FPL input foundation and its focused tests.

## Checkpoint 1.1 evidence

- Runtime source identifiers: `CREDENTIALS_DIRECTORY/the_odds_api_key` (preferred) and process-scoped `DMF_PULSE_ODDS_API_KEY` fallback.
- No API-key CLI option exists.
- Diagnostic: `dmf ingest odds credential-status --output json`; output is one boolean field only.
- Focused tests: `97 passed` (new credential/CLI tests plus affected odds foundation, 429, public-contract and non-PostgreSQL security tests).
- PostgreSQL-only security tests were not run at this checkpoint because `DMF_TEST_DATABASE_URL` is unavailable in the execution container; this is classified `RESOURCE_LIMIT`, not product failure.
- Ruff focused files: PASS.
- Actual provider call: not attempted; remains an operator checkpoint.
