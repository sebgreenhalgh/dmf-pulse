# CURRENT-FPL-STATE-001C donor reconciliation

`NO_DIRECT_DONOR`

No historical implementation truthfully represents the bounded 001C operator-declared current
state. The implementation therefore reuses accepted downstream contracts rather than copying a
donor:

- `ingestion.fpl.current`: immutable 001A catalogue, rights, cutoff, and regular-file posture;
- `rules.one_gameweek`: configured squad, formation, bench, and captaincy rules;
- `optimisation.manager_state.selling_price_tenths`: accepted selling-price calculation only;
- `rules.multi_gameweek`: ACTIVE FULL_SEASON transfer-rule compilation and lineage;
- `chips.compiler` and `chips.inventory`: configured chip keys, grants, copies, windows, token
  statuses, legal transitions, and inventory validation;
- `chips.free_hit`: proof that restoration requires permanent squad/bank/purchase-price state.

The Stage-11 `ManagerState`/`OwnershipSpell` model is deliberately not used as an output because
001C cannot truthfully declare ownership start Gameweeks, predecessor nodes, transition IDs, or
historical realised sales.
