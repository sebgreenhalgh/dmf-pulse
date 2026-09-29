# Exact reuse and effective-policy audit

## Effective request limits

The packaged Stage-11 policy starts at 5,000 actions per state and 1,000 returned
root candidates. The private `_stage11_request()` first computes the exact unfiltered
root-action upper bound, raises both limits as required, and for a bounded horizon
sets `max_actions_per_state` to the screen's authenticated maximum combinations.
For L6 those exactness-preserving derived values were 17,000 and 8,386. D6 does not
reduce them and does not alter the candidate screen, protected players, transfer
limit or continuation mode.

## Existing coalescing

The deterministic enumerator already keys nonterminal states with
`continuation_state_fingerprint()` and eligible zero-terminal-value states with
`terminal_decision_fingerprint()`. The latter retains node/rules context, active
squad, bank, free transfers, current prices and exact sale proceeds. A stronger
per-state action-feasibility quotient would need those same legality dimensions;
states that differ in squad, bank, free transfers or sale economics cannot safely
share an action set. No new state/action quotient was introduced.

Validated transitions remain keyed by the actual state hash and action identity.
They are replayed against the actual state when provenance differs; D6 does not
share mutable transition/provenance objects.

## New exact reuse

`_root_sufficient_candidates()` already retains every root action's exact best
policy for all three supported objectives. Consequently, after a complete
deterministic layered frontier, the separate no-transfer solve repeated layered
discovery, transition validation, tactical evaluation and backward solution for a
root family already retained in that frontier. D6 selects the exact
expected-objective zero-transfer family from the complete deterministic frontier
and constructs its baseline diagnostics from that retained exact candidate. The
legacy replay remains for an incomplete frontier and for the generic enumerator,
whose existing authenticated result bytes therefore remain unchanged.

The service and solver share `deterministic_linear_fast_path_selected()` as the
single actual-path predicate. Preference alone is insufficient: an ineligible
request or an evaluator without the squad-only contract retains the generic
enumerator and its independent baseline replay. A regression proves that
`prefer_deterministic_linear=True` on such a fallback is byte-identical to the
ordinary generic result.

Differential tests compare the reused baseline decisions with an independently
solved `root_no_transfer_only=True` frontier and require exact decision equality.
No legal action or transition is removed from the primary exact frontier.

The authenticated `MultiGameweekOptimisationResult.result_sha256` is not a
cross-policy exactness oracle here: it deliberately binds the configured cap,
search-policy hash and physical-work diagnostics, all of which differ between
the immutable-parent, proposed and high-cap probes. The probe therefore hashes
the complete decision-bearing projection (recommendation, no-transfer baseline,
root counterfactual and transfer-count frontier) after excluding only those
expected execution/configuration diagnostics. That decision semantic SHA is
identical for the parent-complete, proposed and every successful higher-cap run.
