# Immutable donor forensics and port disposition

## Pinned lineage

- Stacked parent: `ddd74fe38ddfae3733ad5189b417123477e9f23e`.
- Parent exact-SHA CI: run `33413309522`, completed successfully.
- Donor branch: `readiness/GW1-2026-27-player-role-prior-candidate`.
- Immutable donor HEAD: `f4d75dc5b107901a3619f136c3d3d7d1d7632a3c`.
- The donor branch ref had not moved at startup.
- No donor merge, rebase, or cherry-pick is used. The port is explicit and semantic.

## Inspected checkpoints

- `66c11b81e92cf6bd23f8cc26d13b1dc0225942d0` — initial player evidence allocation candidate.
- `1a3c63c38a302f9fd4088fdb9f3fa049352652f0` — evidence validation.
- `2a5f844038cacc8d60bb219d102056af31d475b0` — governed role-prior calibration.
- `090b14723fcccd15c9e79b2854d89251d433fd64` — serialized role-prior validation.
- `92a2995143a67e78e98e2bd1b203d2c9f231fc6f` — goalkeeper-only saves regression.
- `85f49727990197f6e5609c028a52c2f4f59f427c` — calibrated role-prior evidence.
- `2d5ed24c807e40796aac077d4dba0b6ea1964cd1` — player-evidence governance approvals.
- `98d1bbd6da46da73243fb8daced56a9580e30dae` — historical transient catalogue bridge.
- `e64c748eba5828c8af8faadb55d6d11051737bc2` — governed posterior/allocation publication.
- `b4353dbdcebd31f2a807bee90ec04b3ee8b07389` — penalty overlay hardening.
- `f4d75dc5b107901a3619f136c3d3d7d1d7632a3c` — historical private acceptance.

## Resource finding

The resource described approximately as `player_prior_v1.json` is not present under that literal
name. The relevant immutable donor resources are the role-prior candidate
`evidence/tickets/GW1-PLY-002/GW1_PLAYER_ROLE_PRIOR_CANDIDATE.json`, the initial 599-player
allocation candidate under `GW1-PLY-003`, and the penalty-hardened central/high/low overlays under
`GW1-PLY-004`. The central overlay is the accepted private-world allocation input.

Central overlay facts: schema `gw1-player-allocation-candidate-v1`, status
`CANDIDATE_NOT_ACCEPTED` inside the artifact, 599 profiles, cutoff `2026-08-21T17:30:00Z`,
posterior hash `537b2ab3c19aba381e6020972cd037b3f62665309c423037049020f0d4f0239f`, and artifact hash
`629d6c288f9faa7aa7763f5c578e662511c03d514169f683cbeb6ee81af695be`.

Its separate historical acceptance record has schema
`gw1-player-allocation-human-acceptance-v1`, status `HUMAN_ACCEPTED_PRIVATE_GW1_ONLY`, scope
`PRIVATE_2026_27_GW1_ONLY`, acceptance hash
`39737c6b96e2664f63f19b4ea0c34038d7c0ec5d9afc9f60cc1c6b89749a3352`, and explicitly sets
`production_activation` to false. These facts do not accept this port.

## A/B/C/D disposition

### A — port essentially as-is

- Exact central overlay values, schema name, cutoff, posterior/artifact hashes, source-level
  lineage, weak-role fallback explanations, limitations, goalkeeper-only zero save rates for
  outfield players, and penalty-taker shares.
- Exact historical private-GW1 acceptance record as provenance evidence, without relabelling.
- Canonical JSON hash semantics for both immutable resources.

### B — port with adaptation to current contracts

- Strict artifact/acceptance models and packaged loader move into current `fpl_points` ownership.
- Donor `PlayerAllocationProfile` values feed the already-current Stage-9 allocation contract.
- Old donor UUIDs remain hash/integrity fields only; exact official-FPL source IDs and current
  `CurrentFplInputBundle` identity hashes bind to explicit canonical Stage-7 player/team UUIDs.
- Penalty and goalkeeper regressions harden the current allocator and current event contract.

### C — superseded by the current stack

- Donor Stage-7/current availability, score simulation, deterministic RNG, current FPL parsing,
  service/CLI, and FPL scoring paths are superseded by current Stage 7, current
  `ScoreDistributionService`, current `fpl_points` allocation, and the current rules adapter.
- The historical `availability.current.current_player_id/current_team_id` surrogate identity
  convention is superseded by explicit current canonical UUID binding.

### D — do not port

- Live/history acquisition, raw-history processing, deletion workflow, empirical-Bayes fitting,
  Wyscout calibration scripts, obsolete catalogue persistence/bridge code, donor approvals
  workflow, provider/network surfaces, and donor CLI/evidence plumbing.
- High/low sensitivity worlds are retained as forensic facts but are not runtime defaults for this
  bounded central-prior port.
- No obsolete current-state infrastructure, direct point predictor, optimiser, or production flag.
