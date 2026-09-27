# Stage-11 resource-limit audit

## Finite taxonomy

| Kind | Origin | Historical `NO_INCUMBENT` compatibility |
|---|---|---|
| `PER_STATE_ACTION_COMBINATION_LIMIT` | one state's raw position-compatible action combinations cross `max_actions_per_state` | possible before the first complete root policy |
| `STATE_EXPANSION_LIMIT` | generic recursive memo miss crosses `max_state_expansions` | possible before the first complete root policy |
| `LAYER_REACHABLE_STATE_LIMIT` | layered forward reachability crosses the shared state envelope before tactical evaluation | compatible; necessarily no incumbent in that solve |
| `CUMULATIVE_LEGAL_ACTION_LIMIT` | layered retained legal transitions cross the whole-solve legal-action envelope before tactical evaluation | compatible; necessarily no incumbent in that solve |
| `POLICY_GENERATION_LIMIT` | generated complete policy count crosses `max_policy_candidates` | possible before the first complete root policy; later occurrence can retain an incumbent |
| `PARETO_FRONTIER_LIMIT` | defensive lossless retained-frontier guard crosses `max_policy_candidates` | structurally unreachable under the current shared numeric cap: a frontier is a subset of already generated policies, so `POLICY_GENERATION_LIMIT` fires first; the typed guard remains defence in depth |
| `ROOT_SUMMARY_LIMIT` | lossless root summary crosses `max_returned_root_candidates` | incompatible with historical `NO_INCUMBENT`; this path already has complete candidates |
| `UNKNOWN_RESOURCE_LIMIT` | closed compatibility identity for an unclassified/legacy resource exception | possible but never inferred as a historical cause |

The solver no longer relies on message parsing. Each raised origin carries its enum,
and resource results authenticate the finite kind, all four pre-existing configured
caps, the distinct cumulative legal-action cap, ordinary search counters, peak raw
per-state action combinations, cumulative legal actions and reachable layered states.
D4 copies only these bounded aggregates;
raw termination text never reaches terminal safe JSON.

The exact three-Gameweek stress matrix independently exercises A, B, C, D, E and G
through the public service. Each result proves its finite kind, complete safe-counter
shape and incumbent/no-incumbent coherence. F cannot independently fire under the
current policy because `len(pareto_frontier) <= generated_policy_count` and both use
the same cap; a real three-Gameweek instrumentation test proves this dominance, while
a direct guard test proves the defensive F identity. Both raised and returned-
incumbent no-transfer-baseline exhaustion now fail closed as typed resource results;
an incomplete baseline can no longer be reported as exact success.

## Governance audit

`max_policy_candidates` was incorrectly overloaded as the layered cumulative
pre-tactical legal-action limit. A generated policy and a retained legal transition
are different units and occur at different search stages. The current versioned
policy therefore states `max_cumulative_legal_actions: 524288` separately while
retaining `max_policy_candidates: 250000` unchanged.

The generated D5 three-Gameweek workload requires 320,610 cumulative exact legal
actions. It fails under the legacy 250,000 envelope at 250,036 and completes under
524,288. The smallest power-of-two governance boundary above 320,610 is 524,288,
leaving 203,678 actions (63.5%) of measured headroom. This is a physical exact-work
bound, not candidate pruning. Legacy authenticated v1
policies that omit the new optional field retain their original meaning by using their
sealed `max_policy_candidates` value as the legacy legal-action envelope. The current
policy loader, however, fails closed if the distinct field is absent.

## Exactness

No action, candidate, state, policy or Pareto member is truncated. Every guard still
fails closed before an incomplete search can claim the exact guarantee. Low-envelope
repository stress fails with `CUMULATIVE_LEGAL_ACTION_LIMIT`; the 524,288 and
1,048,576 envelopes both exhaust exactly 320,610 actions and produce the same
cap-independent decision semantic SHA,
`f5b3d892d999e399be67c6137726adb54d136ccc73a40699b19f5d1efe5e2f47`,
including recommendation, no-transfer baseline, root counterfactual and complete
transfer frontier.
