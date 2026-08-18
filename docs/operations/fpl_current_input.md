# Current official FPL input — manual transient operator route

## Scope

This route validates and compiles the current official Fantasy Premier League
bootstrap and fixtures payloads without network access, a database connection,
raw-source retention, derived persistence, caching, backup, or public disclosure.
It is the approved Checkpoint-1.2 route for the `2026/27` EPL target season while
automated official-FPL access remains denied.

The command consumes operator-owned local files, creates a typed bundle in memory,
prints only a non-disclosing summary, and then exits. The local source files must
be deleted by the operator after the result has been inspected.

## Rights boundary

Use only:

```text
fpl_official_private_manual_v1
```

That profile permits manual import, transient processing and private internal use.
It denies automated access and raw storage. Persistent derived storage remains
unresolved and is therefore denied by the fail-closed rights engine.

Do not use `Invoke-WebRequest`, `curl`, a scraper, browser automation, a scheduled
job, or an authenticated FPL session. Do not place the source JSON in Git, the
repository fixture tree, a database, an object store, a backup, or a chat prompt.

## PowerShell procedure

Run these commands from an activated DMF Pulse environment on Windows PowerShell.
The URLs are opened manually in a normal browser because automated access is not
approved.

```powershell
$CaptureRoot = Join-Path $env:TEMP "dmf-pulse-fpl-current"
New-Item -ItemType Directory -Force -Path $CaptureRoot | Out-Null

$Bootstrap = Join-Path $CaptureRoot "bootstrap-static.json"
$Fixtures  = Join-Path $CaptureRoot "fixtures.json"
```

In a normal browser:

1. Open the official FPL `bootstrap-static` resource.
2. Save the response as the exact local path held in `$Bootstrap`.
3. Open the official FPL `fixtures` resource.
4. Save the response as the exact local path held in `$Fixtures`.
5. Record the later of the two actual save times as `captured_at`; do not invent or
   backdate it.
6. Read event `id = 1` from the saved bootstrap payload and copy its exact
   `deadline_time` value as the information cutoff.

Declare the timestamps explicitly:

```powershell
$CapturedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$InformationCutoff = "<EXACT-GW1-deadline_time-FROM-BOOTSTRAP>"
```

Validate each provider resource first:

```powershell
dmf ingest fpl validate `
  --resource bootstrap `
  --input $Bootstrap `
  --contract-version fpl-reference-v1 `
  --output json

dmf ingest fpl validate `
  --resource fixtures `
  --input $Fixtures `
  --contract-version fpl-reference-v1 `
  --output json
```

Compile the governed current-input bundle transiently:

```powershell
dmf ingest fpl current validate `
  --bootstrap $Bootstrap `
  --fixtures $Fixtures `
  --competition-key PL `
  --season-code "2026/27" `
  --captured-at $CapturedAt `
  --information-cutoff $InformationCutoff `
  --rights-profile fpl_official_private_manual_v1 `
  --gameweek 1 `
  --output json
```

A successful result reports only safe metadata, including:

- player, team and fixture counts;
- target Gameweek and official deadline;
- canonical lookup digests for season-scoped source identities;
- canonical position counts;
- integer-tenths price range;
- status counts;
- capture, receipt, cutoff and usable timestamps;
- source payload and semantic hashes;
- data-quality status;
- explicit rights decisions;
- `database_accessed = false`;
- `raw_storage_performed = false`;
- `derived_storage_performed = false`;
- `transport_called = false`.

It does not print player names, availability news, source bodies, source paths,
credentials, or a database reference.

Delete the transient files in the same operator session, whether validation
succeeds or fails:

```powershell
Remove-Item -LiteralPath $Bootstrap -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $Fixtures -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $CaptureRoot -Force -Recurse -ErrorAction SilentlyContinue
```

## Fail-closed conditions

The combined command rejects, among other cases:

- malformed or wrongly shaped JSON;
- missing or duplicate players, teams, fixtures, positions or Gameweeks;
- unknown team, position or Gameweek references;
- non-positive or non-integer prices;
- impossible home-versus-home fixtures;
- missing or malformed GW1 deadline/kickoff times;
- target fixtures scheduled at or before the deadline;
- post-cutoff capture, receipt, availability evidence or cutoff metadata;
- non-EPL or non-`2026/27` metadata;
- any rights profile other than the approved official manual profile.

## Deliberate limitations

This checkpoint does not retrieve live data, persist canonical entities, resolve
cross-provider identities, model availability/minutes, calculate projections,
run an optimiser, recommend a squad, or call The Odds API. The next implementation
checkpoint is **Checkpoint 1.3 — Live The Odds API Input Foundation**.
