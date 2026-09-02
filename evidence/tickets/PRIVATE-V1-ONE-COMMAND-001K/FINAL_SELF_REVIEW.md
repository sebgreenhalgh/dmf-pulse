# PRIVATE-V1-ONE-COMMAND-001K final self-review

## Scope and correctness

- The immutable parent and branch match the ticket.
- The full selectable incoming universe remains hash-bound in the execution input and all current
  players remain in the Stage-9/Stage-11 catalogue.
- Transfer counts are derived from manager free transfers and compiled rules; no GW3 special case
  exists.
- Zero, one and two transfers remain optional. Transfer hits still use the compiled transition
  implementation.
- Heuristic selection is explicit in the policy rationale, optimiser assumptions, warning set,
  action-space disclosure and human report. No global-optimum claim is emitted.
- Exact Stage-10 evaluation and the existing Stage-9 joint scenarios remain unchanged.

## Search safety

- Certified dominance requires identical club, position and appearance vectors, no higher price,
  pointwise no-worse scenario points and at least one strict price/points improvement.
- Heuristic metric boundaries do not use ownership, names, catalogue order or player IDs; all ties
  at a boundary survive, with a fail-closed overall cap.
- Position balance is generated directly. Existing exact transition validation checks bank,
  selling/buying prices, club quota, duplicates, current ownership and purchasability before Stage
  10.
- The cache key is root node plus canonical squad IDs, which is exactly the Stage-10 dependency.

## Remaining limitation

`ONE_GAMEWEEK_ZERO_TERMINAL_VALUE_OBJECTIVE` remains explicit. The private shortcut does not value
preserving a free transfer for the next Gameweek and is not the full DMFP-12 rolling-horizon
optimiser.

## Release safety

No credential was read or printed, no provider body or private state was persisted, and no PR,
merge, tag or activation was performed. Exact-SHA CI and the existing-runtime live boundary are
recorded separately.
