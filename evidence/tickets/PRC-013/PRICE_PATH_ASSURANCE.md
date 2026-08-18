# Price-path assurance

Paths recompute the three-way hazard after every event, retain event-dependent recurrent state,
and enumerate every configured branch exactly. Bounds move impossible rise/fall mass to no-change.
All prices are integer tenths, PMFs sum exactly to one, expected prices are derived from PMFs, and
repeat-rise, repeat-fall and rise-then-fall paths retain positive mass. Same inputs/configuration
produce the same sealed distribution.
