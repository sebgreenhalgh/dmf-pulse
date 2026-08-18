# The Odds API runtime credential

DMF Pulse never accepts the provider key as a CLI option and never stores it in
Git, committed configuration, evidence, request fingerprints, sanitized URLs,
or logs.

For one PowerShell process/session, set the operator-provided key at runtime:

```powershell
[Environment]::SetEnvironmentVariable("DMF_PULSE_ODDS_API_KEY", "<YOUR_KEY_HERE>", "Process")
```

Confirm only whether a syntactically valid credential is configured:

```powershell
dmf ingest odds credential-status --output json
```

The diagnostic emits exactly `{"configured":true}` or
`{"configured":false}`. It never prints the key, its length, a hash, its
source, or a validation reason.

On a Linux production host, the preferred DMFP-17 route is a systemd credential
named `the_odds_api_key` made available through `CREDENTIALS_DIRECTORY` (for
example with `LoadCredentialEncrypted=`). When that directory is present, DMF
Pulse reads only that bounded regular file and does not fall back to the process
environment.

Unset the PowerShell fallback after the operator run:

```powershell
Remove-Item Env:DMF_PULSE_ODDS_API_KEY -ErrorAction SilentlyContinue
```
