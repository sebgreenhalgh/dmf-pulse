# Genuine run attempt

- Attempt date: 2026-09-02
- Runtime: Windows, CPython 3.13.9
- Source-tree public bootstrap and fixtures: PASS
- Source-tree `CurrentFplInputBundle` compilation: PASS
- External installed-wheel public bootstrap and fixtures: PASS
- External installed-wheel `CurrentFplInputBundle` compilation: PASS
- Detected target Gameweek: 3
- Canonical game-settings JSON bytes: 1,052
- Game-settings semantic SHA-256: `62cbe4f8e9b01faeee8e78e054839e68c78b8d9d03484498e4e2ee92d56e816f`
- Public-first snapshot endpoint classes before auth: `BOOTSTRAP`, `FIXTURES`, `ENTRY`, `HISTORY`, `TRANSFERS`, `PICKS`
- Public-first snapshot next blocker: `CREDENTIAL_MISSING: DMF_FPL_BEARER_TOKEN is missing.`
- Official-FPL raw bodies retained: 0
- Authenticated manager bodies retained: 0
- Secret values retained or displayed: 0
- `DMF_FPL_BEARER_TOKEN` presence: false
- `THE_ODDS_API_KEY` presence: false
- Full command shape: `dmf pulse --entry-id <operator-entry-id>`
- Full-command result: blocked before provider reads; no synthetic input was relabelled as real
- Exact full-command output: `THE_ODDS_API_KEY is missing.`

The live game-settings and bundle hashes are transient observations rather than retained provider
content. No browser store, login state, response body, credential or runtime entry identifier was
read from or written to repository evidence.
