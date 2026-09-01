# Genuine run attempt

- Attempt date: 2026-09-01
- Runtime: Windows, CPython 3.13.9
- Public bootstrap through source-tree `DirectFplClient`: PASS, non-zero body
- Public fixtures through source-tree `DirectFplClient`: PASS, non-zero body
- Public bootstrap and fixtures through external installed wheel: PASS, non-zero bodies
- Official-FPL raw bodies retained: 0
- Authenticated manager bodies retained: 0
- Secret values retained or displayed: 0
- `DMF_FPL_BEARER_TOKEN` presence: false
- `THE_ODDS_API_KEY` presence: false
- Full command shape: `python -c "from dmf_pulse.cli.app import main; main()" pulse --entry-id <operator-entry-id>`
- Full-command result: blocked; no synthetic input was relabelled as real
- Exact full-command output: `THE_ODDS_API_KEY is missing.`

Smallest next runtime blocker: `THE_ODDS_API_KEY` is absent. Odds acquisition was not changed or
diagnosed by this transport-only ticket. Authenticated current-team access will separately require
the existing `DMF_FPL_BEARER_TOKEN` or hidden prompt if the run advances that far.
