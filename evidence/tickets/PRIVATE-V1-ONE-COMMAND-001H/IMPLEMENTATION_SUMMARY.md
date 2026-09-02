# PRIVATE-V1-ONE-COMMAND-001H implementation summary

The current Stage-7 adapter now commits each independently sampled minute vector, then solves an
exact bounded bipartite matching problem over the fixed accepted START/BENCH/OUT roles. The legal
baseline keeps starters for 90 and benches unused; compatible starter/bench pairs may replace that
baseline at integer minutes 1 through 89. Dynamic programming minimizes total absolute deviation,
then substitution count, then stable identities and time. Goalkeepers match only goalkeepers;
outfield players match only outfield players. Every result is revalidated as a paired path totaling
990 minutes before it can enter the fixture input.

The substitution limit is loaded from a strict, hash-sealed wheel resource bound to Premier League
Handbook 2026/27 Rule L.29 rather than treated as a universal football constant. Exceptional
concussion/additional substitutions are explicitly not modelled by this ordinary scenario adapter.
The existing Stage-7 dataset, model artifact, PMFs, expected minutes, role probabilities, scenario
IDs and original deterministic draws are unchanged. Safe reconciliation metrics and both original
and reconciled vector hashes are embedded in the fixture semantic identity.

Stage 9 now carries an exhaustion-policy enum whose default is `BLOCK`. The private service selects
the goal-share proxy policy only for current hierarchy inputs under
`PRIVATE_TRANSIENT_NO_RETENTION`. The shared scored/extra penalty resolver preserves priority:
current on-pitch order, positive historical penalty role, then the explicitly opted-in positive
on-pitch goal-share proxy. It neither mutates `penalty_taker_share` nor invents equal or identity-
based mass. Proxy use is propagated through fixture, gameweek, decision and user report warnings.

No FPL/Odds transport, authentication, market, Stage-8 probability, hierarchy extraction, donor
prior, optimiser, captaincy or chip implementation changed. Ticket evidence contains no provider
body, credential, entry identifier, manager squad, price or player identity.
