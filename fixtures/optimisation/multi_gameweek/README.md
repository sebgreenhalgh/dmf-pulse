# OPT-011 synthetic/reference fixtures

These fixtures are TEST/REPLAY-only. They use a schema-v1.1 `REFERENCE_ONLY`
ruleset with integer tenth-price units, configured half-profit/full-loss selling
semantics, a five-FT cap, and a four-point paid-transfer hit. They do not claim
target-season activation.

`request.json` is a deterministic two-Gameweek price-route case. The current
transfer is optimal because the supplied next-node price state makes the later
route unaffordable. Every tactical value embeds a canonical Stage-10 plan built
from a Stage-9 `GameweekPointScenario`; Stage 11 does not duplicate tactical
scoring.

## Adversarial corpus

The `adversarial/` directory freezes these 20 independent requests:

1. `simple_one_ft`
2. `roll_ft`
3. `rational_hit`
4. `retained_selling_profit`
5. `price_fall`
6. `repurchase_resets_cohort`
7. `funding_transfer_bundle`
8. `price_change_blocks_later_route`
9. `injury_revealed_after_current_decision`
10. `postponed_reassigned_fixture`
11. `horizon_reversal`
12. `futures_identical_until_revelation`
13. `clairvoyance_trap`
14. `terminal_value_reversal`
15. `tied_plans`
16. `malformed_scenario_probabilities_tree`
17. `illegal_manager_state`
18. `infeasible_future_state`
19. `resource_limit_incumbent`
20. `no_materially_distinct_alternative`

`expected_summaries.json` binds each request to its deterministic request/result hashes,
backend status, root action and objective. The target ruleset remains `REFERENCE_ONLY` and
production-ineligible.
