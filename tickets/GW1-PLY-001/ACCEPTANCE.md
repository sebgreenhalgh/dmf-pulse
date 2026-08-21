# GW1-PLY-001 candidate boundary

This branch is an **implemented candidate, not a human-accepted player model**.
It starts at `2ca0e32b32503684d15b70d5c9fce506845939c0` and may be reviewed only
for bounded private 2026/27 GW1 decision-support preparation.

`PLAYER_HISTORY_RIGHTS_APPROVAL = NOT_YET_RECORDED`.

The future source is the official-FPL element-summary template, restricted to
the `history_past` node. The operator command requires an explicit
hash-bound approval file, its expected hash, current mapped player catalogue,
information cutoff, maximum count, terms fingerprint and `POSTERIOR_ONLY`
retention before it can even construct a transport. `--execute-network` is a
further explicit action and was not used for this ticket.

This ticket accepts neither a real history capture nor a current-player
allocation. It also does not accept Wyscout/Pappalardo role-prior data:
`ROLE_PRIOR_REAL_CALIBRATION = SEPARATE_CHECKPOINT`.

The only permitted next state is:

`READY_FOR_PLAYER_HISTORY_RIGHTS_APPROVAL_AND_CAPTURE`
