# Checkpoint 1.3 — live The Odds API operator contract

This is the accepted PowerShell path for one current, provider-native English
Premier League `h2h` snapshot. It does not perform canonical FPL fixture or team
mapping, market consensus, probability conversion, projections, optimisation, or
publication.

`REAL_CREDENTIALLED_PROVIDER_CALL = OPERATOR_CHECKPOINT`

## 1. Enter and install the repository environment

```powershell
Set-Location "<PATH_TO_DMF_PULSE>"
uv sync --all-groups --frozen
. .\.venv\Scripts\Activate.ps1
```

The supported package requires Python 3.13 and installs the `dmf` console command.

## 2. Configure the process-scoped Odds API credential

Set the provider key only for the current PowerShell process:

```powershell
$env:DMF_PULSE_ODDS_API_KEY = "<YOUR_KEY_HERE>"
```

The key is not accepted as a CLI option and must not be written to Git,
configuration, evidence, URLs, or logs.

## 3. Run the non-disclosing credential diagnostic

```powershell
dmf ingest odds credential-status --output json
```

The JSON result is `{"configured": true}` or `{"configured": false}`. It does
not disclose the key, its length, source, prefix, suffix, hash, or validation
reason. Continue only when `configured` is `true`.

## 4. Configure the database reference

The CLI accepts only the reference `env:DMF_TEST_DATABASE_URL`; it does not
accept a PostgreSQL URL or password as a command option. Configure the referenced
process environment and migrate the repository database:

```powershell
$env:DMF_ENVIRONMENT = "TEST"
$env:DMF_TEST_DATABASE_URL = "<POSTGRESQL_URL>"
uv run alembic upgrade head
```

Keep the real database value out of examples, logs, evidence, and the
`--database-url-ref` argument. The snapshot command below contains only the
reference.

## 5. Create a fresh cutoff and run the exact EPL snapshot command

Generate the cutoff immediately before the call. The small forward execution
window prevents a live request from being represented as a historical
observation and avoids the cutoff passing before transport begins.

```powershell
$AsOf = (Get-Date).ToUniversalTime().AddMinutes(10).ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
$SnapshotJson = dmf ingest odds snapshot --provider the_odds_api --competition-key PL --sport-key soccer_epl --region uk --market h2h --as-of $AsOf --database-url-ref env:DMF_TEST_DATABASE_URL --output json
$SnapshotExitCode = $LASTEXITCODE
$SnapshotJson
$Snapshot = $SnapshotJson | ConvertFrom-Json
```

Do not reuse an old `$AsOf`, choose a past cutoff, or backdate a live
observation. The command takes no API-key argument.

## 6. Identify a successful provider-native result

A usable run has exit code `0`, top-level `status` equal to `COMPLETE`, no
top-level `error`, and no quality blockers:

```powershell
$SnapshotExitCode
$Snapshot.status
$Snapshot.error
$Snapshot.current_input.contract
$Snapshot.current_input.identity_scope
$Snapshot.current_input.provenance.canonical_fpl_fixture_mapping_performed
$Snapshot.current_input.provenance.raw_payload_retained
$Snapshot.current_input.quality
```

The expected acceptance values are:

- `contract = ODDS_PROVIDER_CURRENT_INPUT`;
- `identity_scope = PROVIDER_NATIVE_UNMAPPED`;
- `canonical_fpl_fixture_mapping_performed = false`;
- `raw_payload_retained = false`;
- `quality.blockers` is empty.

The current input preserves provider event IDs, kickoff times, provider home and
away text, bookmaker identity and update time, market update state/time, outcome
names, decimal prices, request/receipt/capture/cutoff/usable timestamps, quota
state, rights decisions, configuration hashes, a secret-free request
fingerprint, and lifecycle quality. It does not create canonical FPL fixture or
team mappings, or canonical market/odds rows.

## 7. Inspect quota evidence

```powershell
$Snapshot.current_input.quota | Select-Object remaining, used, configured_request_cost, provider_last_request_cost, observed_at, source
```

For the accepted request, `configured_request_cost` and
`provider_last_request_cost` are both `1`. A low remaining balance is operational
evidence; a zero balance blocks transport with `QUOTA_EXHAUSTED`.

## 8. Controlled failure diagnostics

Every controlled failure is JSON and secret-safe. Inspect:

```powershell
$Snapshot.status
$Snapshot.error.code
$Snapshot.error.message
$Snapshot.error.retryable
$Snapshot.error.transport_called
$Snapshot.quality
```

| Category | Repository error code(s) | Operator response |
|---|---|---|
| Operator configuration | `CREDENTIAL_UNAVAILABLE` | Set a valid process credential, rerun `credential-status`, then retry. |
| Rights | `RIGHTS_BLOCKED` | Stop; do not bypass the active Rights Profile. |
| Quota | `QUOTA_EXHAUSTED`, `HTTP_429` | Stop repeated calls; inspect quota and retry only when permitted. |
| Provider/network | `HTTP_4XX`, `HTTP_5XX`, `CONNECT_TIMEOUT`, `READ_TIMEOUT`, `TOTAL_TIMEOUT`, `TLS_ERROR`, `REDIRECT_BLOCKED`, `CONTENT_TYPE_INVALID`, `SOURCE_UNAVAILABLE` | Preserve the JSON diagnostic; do not expose request credentials or provider bodies. |
| Temporal | `POST_CUTOFF` | Generate a new current `$AsOf`; never backdate or claim the failed call for the old cutoff. |
| Data quality | `QUALITY_BLOCKED` | Do not use the observation; inspect the blocker and retain the fail-closed result. |

Provider-shaped validation can additionally reject malformed JSON, duplicate
keys, oversized payloads, incomplete `h2h` books, impossible timestamps, or
unsupported configuration. None of these states authorises manual alteration of
the provider payload.

## 9. Provider, temporal, rights, and storage contract

The packaged provider configuration is:

- provider `the_odds_api`, API `v4`;
- `https://api.the-odds-api.com/v4/sports/soccer_epl/odds`;
- sport `soccer_epl`, region `uk`, market `h2h`;
- decimal odds, ISO date format, configured request cost `1`;
- at most `2` attempts;
- connect/read/total timeouts of `10`/`20`/`30` seconds.

Temporal acceptance preserves `request_started_at`, `received_at`, `captured_at`,
`information_cutoff`, `usable_at`, event kickoff time, bookmaker timestamps, and
market timestamp state. A provider response-level timestamp is not fabricated
when the provider does not publish one.

The accepted private analytical Rights Profile allows automated access,
transient processing, derived storage, and private internal use. Raw storage is
effectively denied with zero retention. Public display and redistribution are
denied. Backup and model training remain effectively denied while unresolved.
Raw provider bodies are not retained.

## 10. Clear process-scoped values after use

```powershell
Remove-Item Env:DMF_PULSE_ODDS_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:DMF_TEST_DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:DMF_ENVIRONMENT -ErrorAction SilentlyContinue
Remove-Variable AsOf, SnapshotJson, SnapshotExitCode, Snapshot -ErrorAction SilentlyContinue
```

A real credentialled success remains an operator action. Engineering acceptance
validates the installed CLI, option contract, provider-shaped paths, controlled
missing-credential refusal, rights, quota, temporal, packaging, and secret
safety without fabricating a live provider success.
