# Genuine run attempt

- Attempt date: 2026-09-01
- Runtime: Windows, CPython 3.13.9
- Public bootstrap through source-tree `DirectFplClient`: PASS, 1,670,324 bytes
- Public bootstrap parse and semantic hash: PASS
- Detected target Gameweek: 3
- Parsed artifact JSON safety: PASS
- Public bootstrap through external installed wheel: PASS, parsed and hashed
- Official-FPL raw bodies retained: 0
- Authenticated manager bodies retained: 0
- Secret values retained or displayed: 0
- `DMF_FPL_BEARER_TOKEN` presence: false
- `THE_ODDS_API_KEY` presence: false
- Full command shape: `python -c "from dmf_pulse.cli.app import main; main()" pulse --entry-id <operator-entry-id>`
- Full-command result: blocked; no synthetic input was relabelled as real
- Exact full-command output: `THE_ODDS_API_KEY is missing.`

The separate public-first snapshot diagnostic advanced from `BOOTSTRAP` to `FIXTURES` and then
stopped with `INTERNAL_INVARIANT: FPL game settings are invalid`. The locus is
`src/dmf_pulse/ingestion/fpl/current.py::_canonical_game_setting()`: its allowed scalar set omits
`Decimal`, although the strict parser intentionally creates Decimal for JSON fractional numbers.
This follow-on current-input defect is outside the narrow parser-projection hotfix and is not
masked as part of 001C.
