# U.05 screen diagnostics

Primary candidate screens are the union of allowed_transfer_in_ids over the
three horizon nodes, not the unchanged full catalog. Metrics disclose baseline
and shadow counts, intersection, union, additions, removals and exact Jaccard.
Protected candidates are the union of both worlds' accepted one-Gameweek
recommended incoming IDs; retention is disclosed for each screen and jointly.
Node eligibility additions/removals identify redistribution across nodes even
when horizon union membership is unchanged. Only aggregates leave this layer.

The safe terminal summary no longer exposes transfer player IDs or captain/vice
identities. Existing decision records, classification and solves remain intact.
No L8 replay or retrospective decomposition occurred. Optional exact 2x2 solving
is not implemented and remains off by default; normal comparison still has two
worlds. Private execution is sealed before provider access.

Independent review identified and corrected ambient Decimal dependence for
non-power-of-two draw counts and the full-catalog/screen distinction. Fixed
precision60 weights with an exact precision120 residual and validation preserve
reproducibility for counts3/11/13 under precision6. The combined core, closure,
historical authority and canonical two-world regression passed131 tests; the
new integrated identical-catalog/different-screen proof is also checked.
