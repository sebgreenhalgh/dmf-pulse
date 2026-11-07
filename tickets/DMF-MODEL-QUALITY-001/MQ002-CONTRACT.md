# MQ002 owned match-time membership resolver

Owner scope: resume section8 and unchanged accepted data/minutes authority. This
checkpoint implements the pure research resolver and owned counterexamples. It
does not qualify a real source or bind the production Stage7 training path.
Only `OWNED_SYNTHETIC` batches are admitted; real mode fails closed. Do not put
private real history into these fixtures or treat supplied hashes as issuer proof.

Inputs contain an exact player/season/GW aggregate, an independently supplied
complete match-time fixture population for that player/GW, fixture club/event/
finished facts and per-fixture minutes/starts. Every source observation has an
aware UTC usable time and an evidence hash. Current catalogue club is deliberately
absent. Missing/duplicate/conflicting membership, late evidence, unplayed or
postponed fixtures, cross-season/rearranged-GW mismatches, extra participation,
or non-reconciling minutes/starts exclude the entire aggregate with a reason.

No aggregate is divided across double fixtures or capped to90. Doubles need all
explicit per-fixture records and exact reconciliation; a transfer can bind to
different match-time teams even within one GW. A proven blank yields no training
row and remains distinct from missing evidence. An explicit zero-minute start
retains starts1/minutes0 without creating an inferred appearance or current club.

Acceptance: owned transfer/new-club, current-team champion comparison, doubles,
blanks, postponement/rearrangement, ambiguity, duplicates, season/identity/time
boundaries, zero-minute starts and permutation properties. Report accepted,
excluded, blank and unused-fact counts. The same-input champion counterexample
must call the existing `_current_history` function and preserve its result; compare
fixture/team assignment and observed minutes, not invented forecast accuracy.

Before any real integration, exact permitted match-level membership, complete
fixture coverage and research/training/retention purpose must be independently
qualified. The existing current aggregate route and owner recommendation permission
do not supply that authority. Champion source and numerical behavior stay frozen.
