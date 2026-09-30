# Generated-policy governance audit

The immutable parent used `max_policy_candidates` for two different units:

1. cumulative logical `PolicyCandidate` generation across the complete search; and
2. the cardinality of one retained exact Pareto frontier.

This overload is confirmed. D7 introduces authenticated
`multi-gameweek-search-policy-v2`, in which the meanings are explicit:

- `max_generated_policy_candidates`: cumulative logical policies evaluated;
- `max_retained_pareto_candidates`: cardinality of an exact retained frontier; and
- `max_cumulative_legal_actions`: pre-tactical retained legal actions.

The legacy v1 representation remains parseable and authenticated only when it states
the old single field and omits both v2 fields. V2 fails closed if either split field is
missing or if the legacy field is also present. Runtime diagnostics preserve the
legacy configured field for historical artifacts and emit the two split configured
fields for v2 results.

`POLICY_GENERATION_LIMIT` remains the historical finite identity, but v2 diagnostics
bind it to an explicit configured generated-policy limit and observed logical-policy
counter. `PARETO_FRONTIER_LIMIT` binds separately to the retained-frontier limit.
The retained-frontier cap is enforced after every streaming insertion, not only on
the final frontier. Diagnostics expose both cumulative retained-Pareto work and the
distinct peak retained-frontier cardinality, so observed and configured units cannot
be mixed.
