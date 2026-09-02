# PRIVATE-V1-ONE-COMMAND-001G implementation summary

The market producer now quantizes both confidence-scaled totals weights to twelve decimal places
with exact `Decimal` arithmetic and allocates the quantization residual deterministically. The
unchanged grade total is therefore exact for A, B, C and D while targets, uncertainty, caps and
score-model mathematics remain unchanged. Canonical bundle serialization and semantic hashes are
stable across JSON round-trips.

The direct FPL snapshot now extracts positive integer `penalties_order` values from the already
parsed bootstrap payload into a memory-only, raw-bootstrap-hash-bound contract. It ignores only
absent, null and zero roles; rejects unsupported values, duplicate player/team order,
non-contiguous team orders and incomplete current-team coverage; and issues no additional request.

Stage 9 accepts an explicit canonical ordinal hierarchy. Both scored-penalty and extra-penalty
routes select the lowest published order among players actually on pitch at the event time. When
no current role is eligible, the existing governed positive historical donor share is used and
disclosed; if neither source is eligible, `NO_ELIGIBLE_PENALTY_TAKER` remains unchanged. No ordinal
is converted into a probability and no ordinary-goal allocation path changed.

The hierarchy is bound into private execution identity and mapped to fixture-scoped canonical
player/team identities. A current hierarchy emits
`CURRENT_FPL_PENALTY_HIERARCHY_DETERMINISTIC_V1`; actual donor use additionally emits
`HISTORICAL_PENALTY_ROLE_FALLBACK_USED`. Raw provider bodies, credentials, entry identifiers,
squad facts, prices and player identities are absent from ticket evidence.
