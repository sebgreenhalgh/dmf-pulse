# Implementation result

The authenticated current-FPL manager adapter now reconciles provider chip records with the full
governed seasonal inventory by activation window. A current unplayed record binds to the unique
token whose activation window contains the target Gameweek. A played record binds to the unique
token whose window contains the played Gameweek. Provider `number` remains accepted response
metadata and is not treated as a global seasonal token index.

The adapter begins with declarations for every governed token, then overlays uniquely mapped
provider evidence. Consequently the four GW3 provider records produce eight declarations: the
four first-window tokens incorporate provider status and the four unpublished second-window
tokens remain rules-derived `UNAVAILABLE`. At GW20 the current records bind to the second-window
tokens while the unused first-window tokens remain rules-derived `EXPIRED`.

Unknown identities/statuses, incomplete chip types, duplicate or colliding records, duplicate or
multi-event histories, contradictory used/status evidence, played events outside or within
multiple windows, and absent or overlapping current windows fail closed. Governed chip YAML,
manual inventory behavior, transport, authentication, bootstrap, game settings, Odds, score
prior, Stages 7-9, optimiser and captaincy are unchanged.
