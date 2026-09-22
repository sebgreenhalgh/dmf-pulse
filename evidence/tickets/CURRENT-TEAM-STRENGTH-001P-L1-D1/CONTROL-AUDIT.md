# D1 input and derived identity audit

Offline source inspection plus real synthetic screen witness. No historical
private context exists here. This independently proven defect is not proof of
the cause of the consumed historical observation.

## All controls after the authorized correction

| Control | Classification | Equality justification |
| --- | --- | --- |
| algorithm_build | MUST_BE_EQUAL | Same code identity; prior selection does not change code. |
| candidate_policy | MUST_BE_EQUAL | Same declared candidate/input policy, not resulting shortlist. |
| chip_policy | MUST_BE_EQUAL | Same explicit no-chip input. |
| current_source | MUST_BE_EQUAL | One frozen current source. |
| draw_identity | MUST_BE_EQUAL | GW/scenario IDs, outcome draw IDs and weights, not realized points. |
| exact_acceleration | MUST_BE_EQUAL | Same exact execution backend, not tactical outcomes. |
| fixture_order | MUST_BE_EQUAL | Same canonical fixture keys/order. |
| frozen_execution | MUST_BE_EQUAL | Same authenticated original execution, before prior resolution. |
| future_price_policy | MUST_BE_EQUAL | Same no-future-price-change input policy. |
| manager_state | MUST_BE_EQUAL | Same initial manager state. |
| market_constraints | MUST_BE_EQUAL | Identical frozen market constraints in both worlds. |
| ownership | MUST_BE_EQUAL | Same frozen ownership input. |
| player_allocation | MUST_BE_EQUAL | Same governed allocation bindings, not allocated realized events. |
| player_allocation_fallbacks | MUST_BE_EQUAL | Same fallback-assignment input identities. |
| prices | MUST_BE_EQUAL | Full shared catalogue prices at stable GW node IDs, not shortlist. |
| root_randomness | MUST_BE_EQUAL | Same root seed and scenario count. |
| rules | MUST_BE_EQUAL | Same compiled transfer rules. |
| scenario_identity | MUST_BE_EQUAL | Same scenario/index/weight alignment, not transformed outcomes. |
| scenario_policy | MUST_BE_EQUAL | Same Monte Carlo input policy. |
| scenario_tree_policy | MUST_BE_EQUAL | Same fixed no-new-information policy, not derived tree hash. |
| stage7_contexts | MUST_BE_EQUAL | Same already prepared Stage-7 contexts. |
| stage7_inputs | MUST_BE_EQUAL | Same prepared minutes inputs. |
| terminal_policy | MUST_BE_EQUAL | Same transparent terminal policy. |
| work_budget | MUST_BE_EQUAL | D1 input-policy identity plus nonderived effective settings; see split below. |

## Independently reproduced defect and exact split

Parent `_control_hashes` hashed the entire effective `request.search_policy` as
`work_budget`. The private service derives `max_transfers_per_node`,
`max_actions_per_state`, `max_returned_root_candidates` and scope's
`root_maximum_transfers` from candidate counts/protected actions. These values
MAY_LEGITIMATELY_DIFFER_DUE_TO_SCORE_PRIOR. Their containing policy and request
hashes consequently MAY_DIFFER; they are not valid random/input equality tests.

The real `bounded_horizon_screen` witness uses 24 synthetic players, six per
position. Identical means/prices/input policy, with only MID-5 dispersion changed,
retain 12 versus 13 candidates. The actual root-action upper bounds are 7,111
versus 8,386. Parent work-budget identity diverges even though the input policy
does not. D1 hashes the input policy and nonderived effective settings instead.

The split is local to the team-strength comparison, not the ordinary optimiser
or the separate historical four-world comparison. The identity has explicit
version `TEAM_STRENGTH_INPUT_WORK_BUDGET_V1`. It binds packaged input policy,
declared transfer limit, search scope mode, continuation mode (including absence)
and every other effective nonderived search field. It excludes the effective
policy's self-hash and the four derived structures above. Critically,
`continuation_mode` remains a hard input; only its sibling root limit is derived.

Each world's existing `optimiser_request_sha256` still authenticates the entire
derived request. Nothing changes a search limit, objective, feasible action,
projection, classification or threshold. Candidate-screen movement remains
`CANDIDATE_SCREEN_CONFOUNDED`, not a spurious hard-control failure.

The user expressly permits new comparison/control/container hashes. All five
passing 001P cases are checked against exact-parent comparison assembly using
the same genuine current solve results. After substituting only the authorized
control identity, the entire parent and D1 comparison must be equal. Original
parent signatures, fixture results, movements and classifications must match
without substitution. Goldens are not regenerated.

## Common random numbers

Root seed, fixture seed, scenario index, draw namespace, outcome draw ID and
scenario weights remain aligned. The inherited real comparison records actual
scoreline RNG seed/namespace/representative raw draw and proves equality.
Stage-9 seed construction and named allocation streams are unchanged.

Sampled scores, allocated events, FPL points, Stage-8 distributions, Stage-9
projection hashes, optimiser rankings, candidate screens and derived scenario
information-set hashes MAY_DIFFER. They are expected effects, not hard controls.
No input control other than parent work-budget identity was found to indirectly
require shortlist equality.
