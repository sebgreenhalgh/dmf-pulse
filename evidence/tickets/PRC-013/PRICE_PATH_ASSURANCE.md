# Price-path assurance

Paths recompute the three-way hazard after every event and retain event-dependent recurrent state.
All configured branches are enumerated exactly; impossible boundary events move to no-change using
the complete configured step. Prices remain integer tenths. PMFs sum exactly to one, expected
prices derive from PMFs, and repeat/opposite-direction paths retain positive mass.

The sealed artifact declares its step, bounds, initial Gameweek event counts and model lineage.
Rehydration reconciles horizon order/counts, scenario uniqueness/length/transitions/support, final
PMF, any-event and multiple-event probabilities. Adversarial mutations are rejected.
