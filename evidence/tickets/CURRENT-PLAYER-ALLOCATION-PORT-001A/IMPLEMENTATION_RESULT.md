# CURRENT-PLAYER-ALLOCATION-PORT-001A implementation result

Implementation checkpoint: `682d75e4da766d1eac75ebe32b5f3578c787c4db`, a normal direct
descendant of immutable stacked parent `ddd74fe38ddfae3733ad5189b417123477e9f23e`.

## Delivered capability

The immutable donor central overlay and its separate historical acceptance record are preserved
byte-for-byte in both tracked configuration and package resources. The strict loader validates
schema, canonical IDs, finite numeric fields, ordering, one-to-one lineage, exact semantic hashes,
scope, cutoff, and the non-production historical acceptance state.

The new current binding uses `CurrentFplInputBundle` official element/team identities and an
explicit caller-owned canonical UUID map. Historical donor UUIDs validate provenance only; they
never become runtime Stage-7 player IDs. Missing, duplicate, stale-team, malformed, post-cutoff,
wrong-scope, or incomplete mappings block with typed errors. There is no name/fuzzy match or
silent zero/uniform replacement.

The existing current allocator was adapted rather than replaced. It now canonically orders every
candidate set, retains exact on-pitch intervals in generated player vectors, models explicit
penalty and goalkeeper-save links, rejects missing governed own-goal/penalty/shooter shares, and
independently reconciles aggregate goals, assists, own goals, penalty outcomes, saves, compatible
shots, teams, positions, and timing in `FixtureEventScenario`.

The current `FplPointsService` remains the service/API. Current Stage-8 score cells remain team
score authority, and the existing rules adapter remains the only FPL scorer. Scenario weights,
integer component scores, joint BPS/bonus, player-by-scenario matrix rows, and matrix-derived
marginals survive unchanged for downstream optimisation.

## Exact resources and principal code

- `config/models/gw1_private_player_allocation_prior_v1.json` and packaged counterpart: raw
  SHA-256 `995d0166c7d5cdd86f18948f6d374044da116881758622fc98f1ca3718c5fae0`.
- `config/models/gw1_private_player_allocation_acceptance_v1.json` and packaged counterpart: raw
  SHA-256 `67b69a2c04171ceacd8bcc3667d058e4b2d1864442dc95f3e1c9371f9cd58224`.
- Central schema `gw1-player-allocation-candidate-v1`, 599 profiles, artifact SHA-256
  `629d6c288f9faa7aa7763f5c578e662511c03d514169f683cbeb6ee81af695be`.
- Historical acceptance schema `gw1-player-allocation-human-acceptance-v1`, acceptance SHA-256
  `39737c6b96e2664f63f19b4ea0c34038d7c0ec5d9afc9f60cc1c6b89749a3352`.
- `src/dmf_pulse/fpl_points/player_prior.py` owns strict loading and exact current identity/profile
  binding. `models.py`, `allocation.py`, and `service.py` retain coherent event and lineage state.
- `event_allocation_baseline.yaml` is explicitly versioned
  `pts-event-allocation-current-player-port-001a-v1` and remains temporary TEST/REPLAY modelling,
  never an FPL ruleset or production calibration.

## Deliberately rejected donor surface

No donor merge, rebase, or cherry-pick occurred. Donor Stage-7, score simulation, FPL scoring,
current catalogue bridge/persistence, provider/history acquisition, calibration scripts,
approval workflow, CLI plumbing, high/low runtime worlds, and optimiser code were not ported.
`DONOR_FORENSICS.md` records the complete A/B/C/D disposition and full inspected SHAs.

## Status

`CURRENT_PLAYER_ALLOCATION_PORT_001A_IMPLEMENTED_PENDING_INDEPENDENT_REVIEW`

The donor prior carries confidence grade E and historical private-GW1 provenance. The port is not
production-ready, newly accepted, human-accepted, merged, tagged, or production-active.
