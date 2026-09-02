# PRIVATE-V1-ONE-COMMAND-001L implementation summary

- Added `ExactTacticalNodeKernel`, which builds the canonical player index, exact common integer
  scenario-weight denominator, grouped appearance states and weighted player-point numerators once
  per Stage-11 node.
- Reused captain/vice and goalkeeper pair values across squads, cached position-level autosub
  resolutions, and interpreted each XI/appearance state once for all six outfield bench orders.
- Preserved integer/Fraction exactness, deterministic tie behavior and every declared logical
  exhaustive-search counter. No float objective or approximation was introduced.
- Re-evaluated each selected tactic with the existing canonical scenario evaluator and failed
  closed on any objective disagreement before publication.
- Added canonical `Stage10TacticalAdapter.evaluate_many`, independent of input order, and prefilled
  the existing private `(node, canonical squad IDs)` memo before unchanged Stage-11 selection.
- Added truthful Stage-10 `N/total` milestones and separate Stage-10-ready and Stage-11-selection
  timings. No percentage or ETA is fabricated.
- Retained the complete 001K incoming-player shortlist and legal transfer-action scope. No Stage
  7/8/9, odds, prior, penalty, captain, autosub-rule, tactical-legality, objective or transfer
  semantic changed.
