# Candidate weak support prior — not accepted, not implemented

Status: **BLOCKED; NO NUMERICAL ARTIFACT ISSUED**

The requested broad generic pre-season support-prior candidate cannot be
derived honestly from the pinned repository material. The only identified
pinned training lineage is the Stage-7 synthetic/replay availability dataset
`1466a5dcc9104a2d26f9c6b286d2717b6460423503026f05a58d3a26de040be3`.
It supports the minutes baseline only; it is not a rights-reviewed historical
team-goal, player-goal, or player-assist calibration sample.

No repository-contained, rights-reviewed open-data historical score/event
sample, source license record, calibration split, or prospective calibration
report was found for the requested values. Producing generic league rates,
position/role shares, smoothing strengths, or uncertainty parameters would
therefore invent numerical evidence.

The existing `INDEPENDENT_POISSON_V1` score prior remains a Stage-8 regularizer
only. Under ADR-MKT-007, current H2H plus available O/U 2.5 consensus supplies
the fixture-specific market evidence. This document does not activate or alter
that prior.

Before issuing a candidate, supply or pin an open-data sample with: exact
source/version/hash and licence; event/fixture identity policy; leakage-safe
season/time split; promoted/new-player policy; team-score and player-allocation
calibration outputs; and independent human review. A candidate must remain
`CANDIDATE`, be outside the accepted current-event artifact, and carry no
activation path until separately accepted.
