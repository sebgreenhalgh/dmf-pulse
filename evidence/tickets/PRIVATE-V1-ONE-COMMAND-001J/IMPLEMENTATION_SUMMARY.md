# PRIVATE-V1-ONE-COMMAND-001J implementation summary

`CurrentModelWeightedScenario` now owns the internal current-model scenario envelope. It retains
the accepted player, role and minute semantics but does not inherit the manual transient input's
40-player ceiling. The current object has no new arbitrary observed-size cap because it is built
only after the governed, bounded official-FPL parser and canonical mapping path. The public manual
model is unchanged.

The current team contract still validates the exact 256 scenario IDs and counts, identical roster
and positions across samples, unique players, 11 starters, nine bench players, starting and bench
goalkeeper structure, hard-ineligible OUT status, legal paired substitutions, and 990 minutes.
Reconciliation constructs the current-specific scenario type and preserves every OUT row. Its
player-minute hash includes player identity, position, role and minutes for the complete roster.

The one-command Stage-7 builder now accepts the existing run-local progress observer. Each fixture
has an outer total timer containing separate home and away prediction timers plus a reconciliation
phase. BLOCKED predictor results become their existing safe typed code. Model exceptions keep the
generic model-block code, while structural adaptation/reconciliation errors use the distinct
`CURRENT_STAGE7_SCENARIO_ROSTER_INVALID` code. No private identity is emitted.
