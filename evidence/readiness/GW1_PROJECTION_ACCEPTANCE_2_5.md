# GW1 Checkpoint 2.5 - projection acceptance

## Result

- Engineering implementation - `COMPLETE`.
- Real current projection - `NOT_EXECUTED / BLOCKED_CURRENT_EVENT_PRIOR_ARTIFACT`.
- Classification - `PRESEASON_DECISION_SUPPORT / NON_PRODUCTION`.
- Rules - exact VERIFIED `fpl-2026-27` PLAYER_POINTS capability; global ACTIVE
  or human activation was neither inferred nor created.

## Acceptance boundary

`assess_current_projection` independently serializes/revalidates the complete
Stage-8 and Stage-9 bundles and requires exact source semantic and decision-time
cutoff equality. It reconciles every official current player to exactly one
projection row and checks official/transient player identity, club identity and
name, position, current price, P(appearance), P(start), expected minutes, and
the embedded Stage-7 player identity. Missing players, unprojected teams,
identity collisions, duplicate output rows, or detached lineage fail closed.

The existing Stage-9 bundle remains the sole source for mean points, full PMF,
quantiles, threshold probabilities, joint scenario identity, numerical
uncertainty, rules/config hashes and event provenance. No xP formula or
deterministic shortcut was added. The acceptance result is non-disclosing and
contains counts/hashes only.

An initial-squad run is accepted only when the governed Monte Carlo diagnostic
is `PASS`. The 32-scenario engineering fixture correctly returns
`UPSTREAM_MONTE_CARLO_CONTINUE`; it produces no portfolio or receipt. Cold-start
and synthetic TEST/REPLAY training limitations remain explicit warnings.

## Hostile checks

- No synthetic odds fallback, all-start assumption, 90-minute default, fuzzy
  identity, missing-player skip, handcrafted xP, rules activation, persistent
  FPL detail, or partial output exists in the adapter.
- Stage-6 through Stage-9 models continue to enforce complete mapped fixtures,
  cutoff-safe observations, normalized distributions and hash-bound rules/model
  configuration.
- Material remediation: an early implementation skipped official players whose
  teams were absent from Stage 7. This now blocks acceptance explicitly.

## Validation

- Final current/Stage-12/orchestration group - `160 passed` in `533.26s`.
- Exact current Stage-7 through Stage-9 branch gate - `34 passed` in
  `607.61s`; `92.27%` branch-aware coverage across `1,107` statements and `200`
  branches.
- Frozen Stage-9 resource assurance - `PASS`.
- Final exact-SHA Linux validation - `PENDING_FINAL_PUBLICATION`.
