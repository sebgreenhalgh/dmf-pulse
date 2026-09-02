# Implementation result

The Odds request boundary now accepts only aware whole-second commence datetimes. It converts
whole-second non-UTC values to UTC without float timestamps and serializes the provider-required
`YYYY-MM-DDTHH:MM:SSZ` form. Fractional or naive values fail as configuration errors instead of
being silently rounded or sent to the provider.

Current Odds provenance still requires exactly one each of `regions`, `markets`, `oddsFormat`,
`dateFormat` and `commenceTimeFrom`, and now permits exactly one optional `commenceTimeTo`.
Duplicates, unknown parameters, noncanonical commence timestamps and an upper bound that is not
later than the lower bound fail closed. The lower bound remains exactly aligned with the temporal
information cutoff.

The literal CLI establishes one canonical whole-second UTC `run_at` before constructing the
one-command request. That same instant reaches the Odds lower bound and current-input temporal
cutoff. The existing upper bound remains the latest target-Gameweek kickoff plus one second, as
proved at the one-command boundary.

Provider transport/authentication, FPL manager/chips, rights, market quality, consensus, score
prior, Stages 7-9, optimiser and captaincy are unchanged. No live provider body or secret was
read, persisted or printed.
