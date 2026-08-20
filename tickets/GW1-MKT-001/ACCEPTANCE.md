# GW1-MKT-001 acceptance record

Implementation status: **READY FOR INDEPENDENT REVIEW; NOT HUMAN-ACCEPTED**.

The bounded path is accepted for test only when it proves all of the following:

- Decimal-valued current FPL settings compile transiently without JSON failure.
- The provider contract requests UK `h2h,totals` and verifies response quota
  cost two without a real request.
- H2H normalisation remains fail-closed, while absent/bad/stale totals are
  explicit optional degradation rather than a silent substitution.
- Valid two-way O/U 2.5 books are de-vigged per operator and retained with
  their own source hashes and 90-minute settlement.
- Existing Stage-8 receives both families as one constraint set and existing
  Stage-9 receives that one score matrix; no alternate simulator/optimiser is
  present.

## Recorded local validation

2026-08-20, before publication:

```text
uv run pytest -q [15 bounded current-market/Stage-8/Stage-9 paths]
PASS: 319 passed in 266.49s

uv run ruff format --check src/dmf_pulse tests scripts
PASS: 528 files already formatted

uv run ruff check src/dmf_pulse tests scripts
PASS

uv run mypy src/dmf_pulse
PASS: 205 source files

uv run pytest -q tests/unit/markets/test_normalisation.py
tests/unit/markets/test_current_market.py
tests/unit/fpl_points/test_current_football_events.py
PASS: 46 passed in 203.78s

uv build
PASS: wheel and source distribution built

uv run python scripts/validate_repository.py
PASS: 0 errors

uv run python scripts/scan_secrets.py
PASS: 0 findings

clean installed wheel outside source tree
PASS: dmf 0.2.0; ingest odds snapshot --help
```

The dedicated Ubuntu workflow is
`.github/workflows/gw1-market-primary-remediation.yml`. Its exact-SHA result
must pass after the branch is pushed; it is not replaced by this local result.

## Manual review still required

1. Confirm The Odds API plan/terms and the actual EPL response contain legal,
   useful multi-book pre-match `h2h,totals` coverage before any key is used.
2. Inspect the first real operator review for fixture orientation, duplicate
   books, full-time settlement, timestamp/freshness, O/U line, and H2H-only
   fallback annotations.
3. Supply and review a licensed, pinned historical team/player event sample
   before accepting either candidate described in the evidence directory.
4. Independently review this branch. Human acceptance, activation, PR and
   merge are deliberately outside this ticket.
