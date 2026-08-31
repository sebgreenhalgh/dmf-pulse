# PORT.02 player-event allocation invariants

## Current-stack adaptation

The port hardens the existing `dmf_pulse.fpl_points.allocation` boundary; it does not add a
parallel score simulator or FPL scorer. Stage-8 sampled score cells remain authoritative and the
existing `FixtureEventScenario` still feeds the canonical rules adapter.

- Eligible scorer/assister/own-goal/taker/goalkeeper/shooter candidates are canonically ordered by
  player UUID before every weighted draw.
- Missing penalty-taker or own-goal share now raises a typed blocking error. The prior behavior
  that changed the mechanism or substituted goal share was removed.
- `PlayerEventVector` carries the exact Stage-7 interval for generated scenarios. Fixture
  validation independently rejects a goal, assist, own goal, penalty, save, or saved shot outside
  that interval.
- Every scored penalty has one `PenaltyEvent` linked to its one authoritative goal; missed/saved
  penalties create no goal. Each saved penalty links one on-pitch taker, one defending on-pitch GK,
  and one `GoalkeeperSaveEvent`.
- Normal goalkeeper saves are sampled from the governed GK rate, timed inside that GK interval,
  and paired with one on-pitch attacking shot. Governed auxiliary on-target rates select the
  shooter. A visible goal-share proxy exists only for `TEST_SYNTHETIC`; non-test inputs fail closed
  if no compatible shooter share exists.
- The fixture contract reconciles aggregate saves, penalty saves/misses, and goal/assist/own-goal
  vectors to explicit events. Linked saves cannot exceed represented compatible shots on target.
- Only `PlayerPosition.GK` enters the save allocator, protecting the donor goalkeeper-only
  regression even if a hostile outfield profile carries a non-zero goalkeeper rate.

## Proof executed at PORT.02

- `tests/unit/fpl_points/test_allocation.py`: direct goal/assist/own-goal/penalty/save/minute,
  ordering, no-fallback, and deterministic regressions.
- `tests/unit/fpl_points/test_player_event_port_invariants.py`: hostile off-pitch, outfield-GK,
  missing-shot, unlinked-penalty, and wrong-goalkeeper reconstruction failures.
- `tests/property/fpl_points/test_properties.py`: many-seed per-scenario goal conservation,
  scorer/assist timing, goalkeeper-only timed saves, exact aggregate-event reconciliation,
  penalty misses, integer scoring, and worker-partition determinism.
- Complete affected Stage-9 suite: `162 passed` in the isolated Python 3.13 Linux environment.
- Ruff and strict mypy for `src/dmf_pulse/fpl_points`: pass.

This is engineering evidence only. It is not human acceptance or production activation.
