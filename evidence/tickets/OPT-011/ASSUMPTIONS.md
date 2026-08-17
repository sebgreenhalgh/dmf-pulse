# OPT-011 assumptions and interpretations

- Every scenario-tree node is a decision information state. `points_state_id` identifies the
  forecast/value state known at that node; it is not a hidden realised leaf outcome.
- Histories with identical revealed information must be represented by one normalized node. A
  duplicate indistinguishable decision history is rejected rather than allowed to choose a
  leaf-specific action.
- Purchase price belongs to an ownership spell. Selling and later repurchasing creates a new
  spell and does not rewrite the prior spell.
- Prices and bank use integer FPL tenth-units. Affordability never uses binary floating point.
- The synthetic schema-1.1 ruleset is `REFERENCE_ONLY`, production-ineligible and makes no
  target-season claim.
- Stage-10 remains authoritative for XI, formation, bench order, autosubs, captain/vice and
  scenario tactical scoring. Stage 11 consumes canonical Stage-10 plans through an explicit
  adapter.
- The current executable action is the root action only. Future policy is explanatory/contingent;
  the next request is re-rooted after observation and solved again.
- Exact move marginal values are drop-one re-optimisations. Their sum need not be additive;
  residual interaction is reported explicitly for funding bundles and dependent moves.
