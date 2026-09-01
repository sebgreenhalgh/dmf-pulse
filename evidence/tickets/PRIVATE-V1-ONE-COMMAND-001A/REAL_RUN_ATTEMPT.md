# Genuine run attempt

- Attempt date: 2026-09-01
- Command shape: `dmf pulse --entry-id <operator-entry-id>`
- Official-FPL raw bodies retained: 0
- Authenticated manager bodies retained: 0
- Secret values retained or displayed: 0
- `DMF_FPL_BEARER_TOKEN`: absent
- `THE_ODDS_API_KEY`: absent
- Provider calls made by the final command attempt: 0 (credential preflight stopped the run)
- Result: blocked; no synthetic input was relabelled as real

Smallest current blockers: `THE_ODDS_API_KEY` is missing and authenticated current-team access
requires `DMF_FPL_BEARER_TOKEN` (or a hidden interactive token).
