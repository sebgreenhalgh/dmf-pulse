# GW1 Session 1 — Checkpoint 1.2 publication reconciliation

## Recovery result

- Canonical starting head — `d75a172018f932693c4d51dc3d803819075c3cac`.
- Existing Checkpoint 1.1 implementation commit — `448749c072900642a922ae1456d0d30111a3e9ea`.
- Corrupt staged publisher commit — `2a06f154c6ac7f0edef314daea534b916c0a4dad`.
- Recovered prior Checkpoint 1.2 capability commit — NONE.
- Recovered prior Checkpoint 1.2 evidence commit — NONE.
- Resolution — implement and publish only the minimum missing Checkpoint 1.2 capability.

## Capability commit

- Commit — `d8e95a442d24d0547a2b7a5fb585da94f66dcfe4`.
- Changed files:
  - `docs/operations/fpl_current_input.md`
  - `src/dmf_pulse/cli/ingest_cmd.py`
  - `src/dmf_pulse/ingestion/fpl/__init__.py`
  - `src/dmf_pulse/ingestion/fpl/current.py`
  - `tests/unit/cli/test_fpl_current_input.py`
  - `tests/unit/ingestion/test_fpl_current_input.py`

## Contract coverage

The capability validates and compiles a database-free transient bundle containing official player/element, team, position, price, status/availability, fixture, Gameweek/event, deadline and game-setting data. Every entity carries an exact season-scoped provider identity and deterministic canonical lookup digest. The bundle records source and semantic hashes, capture/receipt/cutoff/usability times, configuration hashes, rights decisions and data-quality state.

The service fails closed on malformed JSON, duplicate source IDs, unknown team/position/event references, invalid prices, missing or ambiguous target-Gameweek markers, post-cutoff evidence, naive timestamps, cutoff/deadline violations, symlink inputs, oversized inputs and disallowed rights profiles.

## Rights and persistence

- Allowed — manual import, transient processing, private internal use.
- Denied — automated access, raw storage.
- Unresolved derived storage — treated as denied.
- Network transport — not called.
- Database — not opened.
- Raw storage — not performed.
- Derived storage — not performed.

## Validation evidence

- Focused tests — `36 passed`.
- Wider affected FPL regression — `196 passed, 6 deselected`.
- Ruff format and lint — PASS.
- Strict mypy — PASS.
- CLI smoke and redaction assertions — PASS.
- Publication workflow run — `32182179765`.

## Scope boundary

Checkpoint 1.3 and all later live-odds, mapping, modelling, projection, optimisation, recommendation and production-activation work remain untouched.
