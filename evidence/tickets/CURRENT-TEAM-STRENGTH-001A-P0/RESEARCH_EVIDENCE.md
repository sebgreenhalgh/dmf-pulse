# Accepted precursor research record

The selected provisional shadow policy is
`REGULARISED_TIME_WEIGHTED_INDEPENDENT_POISSON_TEAM_STRENGTH_V1`, trained from `2010/11` on all
eligible results strictly before each forecast cutoff, with 365-day half-life, 12-match effective
attack and defence priors, historical promoted-club cohort centre, and one fitted global home
effect. The future implementation is specified as float64 analytic damped Newton with Decimal
canonicalization only at serialized rate/artifact boundaries and rates in `(0, 8.000000]`.

The existing Stage-8 `INDEPENDENT_POISSON_V1` `ScorePriorRequest` contract remains unchanged.
Hessian/covariance must be retained; plug-in prediction is shadow-only; uncertainty propagation
requires separate ticket `CURRENT-TEAM-STRENGTH-001U` before any production promotion.

Recorded reconstructed out-of-time evidence:

- baseline exact-score log loss: `2.951989`;
- selected model: `2.887816`;
- candidate minus baseline: `-0.064172`;
- 95% Gameweek-block bootstrap CI: `[-0.100400, -0.028708]`.

These values support implementing a shadow challenger. They do not establish production
superiority, authorize fitting in P0, or authorize production promotion.
