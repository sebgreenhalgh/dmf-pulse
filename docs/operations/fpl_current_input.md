# Manual transient current FPL input

`dmf ingest fpl current validate` compiles an operator-supplied official FPL bootstrap and
fixtures pair in memory and prints only a disclosure-minimized summary. It supports the explicit
Premier League `2026/27` ingestion season and any positive target Gameweek that the supplied
bootstrap marks exactly as current or next.

This command does not retrieve FPL data, use an authenticated session, contact a database, or
write either raw or derived current state. It does not provide manager-owned state or FPL-to-Odds
identity.

## Authority and non-negotiable boundary

The current `fpl_official_private_manual_v1` profile allows manual import, transient processing,
and private internal use. Automated access and raw storage are denied; derived-storage rights are
unresolved and therefore denied by the runtime decision.

Accordingly:

- capture the two resources manually in a normal operator-controlled browser;
- do not use `curl`, `Invoke-WebRequest`, a scraper, browser automation, a scheduled job, or a
  second network client;
- do not use FPL credentials, cookies, login state, or an authenticated manager session;
- do not place payloads in the repository, database, object store, cache, backup, chat, ticket, or
  evidence;
- keep the files only for the shortest local processing window; and
- delete both files after success or failure.

The software does not own the input files and cannot truthfully delete them. Every summary reports
`operator_delete_required=true`; that is a required operator action, not a deletion receipt.

## Capture and validate

Record the real capture time when the manual browser save completes. Select an explicit
information cutoff no later than the target Gameweek deadline. Do not derive the target Gameweek
from the wall clock; choose the official event ID shown in the captured bootstrap.

From a frozen installed environment, validate the resources individually first:

```powershell
dmf ingest fpl validate --resource bootstrap --input C:\private-temp\bootstrap.json --output json
dmf ingest fpl validate --resource fixtures --input C:\private-temp\fixtures.json --output json
```

Then compile the transient pair. This example uses Gameweek 2 only as an illustration:

```powershell
dmf ingest fpl current validate `
  --bootstrap C:\private-temp\bootstrap.json `
  --fixtures C:\private-temp\fixtures.json `
  --competition-key PL `
  --season-code 2026/27 `
  --gameweek 2 `
  --captured-at 2026-08-24T12:00:00Z `
  --information-cutoff 2026-08-28T17:30:00Z `
  --rights-profile fpl_official_private_manual_v1 `
  --output json
```

Inspect only the safe summary. It contains counts, time boundaries, rights outcomes, quality
status, and hashes; it intentionally excludes player names, news, source paths, and source
payload fragments. The complete typed bundle exists only inside the immediate private process.

Finally, delete both manually captured files whether the command passed or failed. Do not retain a
copy in recycle bins, synchronized folders, caches, or backups.

## Fail-closed behavior

The command rejects unavailable, duplicate, oversized, non-regular, or symlink inputs; parser or
schema failures; unsupported competition/season declarations; invalid current/next event flags;
missing or invalid target fixtures; unresolved cross-resource identities; non-positive prices;
post-cutoff receipts or availability evidence; and rights drift.

Additive unknown provider fields produce safe quality warnings. Missing required or structurally
invalid fields remain blocking. A passing summary is not production activation, persistent
ingestion, manager-state verification, or human acceptance.
