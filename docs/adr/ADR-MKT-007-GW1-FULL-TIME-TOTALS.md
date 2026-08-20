# ADR-MKT-007: Bounded current-GW1 full-time totals evidence

Status: implemented under operator authorization; pending human acceptance.

For current GW1 decision support, request The Odds API EPL UK multi-book
`h2h,totals` markets. H2H and complete O/U 2.5 totals are normalised separately
with existing exact-Decimal Stage-6 mathematics, then translated into separate
native Stage-8 constraint rows for a single existing score matrix.

The Stage-8 independent-Poisson matrix is still a prior-backed soft-KL
projection, but it receives both result and total evidence directly. This makes
the current market consensus the fixture-specific evidence and leaves the
accepted score prior as the regularising distribution; it does not introduce a
second score model or a Dixon-Coles/rho claim.

H2H is mandatory. Missing, stale, malformed, or non-2.5 totals are surfaced as
explicit per-fixture limitations and the H2H-only matrix path remains valid.
When both families are used, every residual retains its source Stage-6 result
hash and the combined outer source hash is null rather than concealing lineage.

Scope is deliberately restricted to pre-match full-time 90-minute O/U 2.5.
No player props, team totals, in-play feed, raw-data persistence, database
migration, new dependency, key use, activation, PR, or merge is authorized.
See `tickets/GW1-MKT-001/ticket.yaml` and its authority resolution for the
exact authorization and unresolved review actions.
