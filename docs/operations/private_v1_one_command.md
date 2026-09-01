# Private one-command recommendation

Run before the target Gameweek deadline:

```text
dmf pulse --entry-id <your-entry-id>
```

Set `THE_ODDS_API_KEY` in the process environment. For exact pre-deadline manager state, set a
short-lived `DMF_FPL_BEARER_TOKEN`; in an interactive terminal the command can instead request
it through hidden input. Never put either credential on the command line, in a file, or in a
support report.

The current 2026/27 FPL web application was inspected on 2026-09-01. Its authenticated current
team request uses `GET /api/my-team/{entry_id}/` with
`X-API-Authorization: Bearer <token>`. Public entry, history, transfers and completed picks do
not prove pending pre-deadline changes, so the command does not substitute a previous-GW squad.
A rejected or expired bearer fails with an authentication action instead.

This path is operator-initiated, sequential, low-volume, read-only and memory-only. It cannot
submit transfers, lineup/captain changes or chips. Official-FPL bodies and authenticated manager
facts are parsed transiently and are not cached, written to the database, placed in evidence or
added to replay bundles.

The access profile represents an explicit private project governance decision accepting known
contractual risk around automated extraction. It does not claim Premier League endorsement or
API permission, and it does not authorise commercial, public, scheduled or mass-manager use.

The report starts with the recommendation, squad, XI, bench, captain, vice and aligned
no-transfer comparison. Warnings then disclose model confidence, the historical grade-E player
allocation prior, private VERIFIED-rules authority, accepted FPL access risk and
`NOT_PRODUCTION_ACTIVE` status.
