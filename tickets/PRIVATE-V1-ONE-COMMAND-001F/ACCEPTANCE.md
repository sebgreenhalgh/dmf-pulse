# PRIVATE-V1-ONE-COMMAND-001F engineering acceptance

Generic Odds request construction accepts only timezone-aware exact whole-second commence
boundaries. Accepted instants serialize as canonical UTC `YYYY-MM-DDTHH:MM:SSZ`; non-UTC aware
instants normalize to equivalent UTC, while naive or fractional-second inputs fail closed. The
literal CLI generates one canonical whole-second future information cutoff and passes that exact
instant as one-command `run_at`; no arbitrary external cutoff is silently widened.

Current Odds provenance requires exactly one each of `regions`, `markets`, `oddsFormat`,
`dateFormat` and `commenceTimeFrom`, optionally exactly one `commenceTimeTo`, and rejects duplicate
or unknown names. Both commence values must be canonical UTC whole-second strings. The lower bound
must equal the logical information cutoff and any upper bound must be strictly later. Existing
region, market, format, target-GW upper-bound and provider-native quality contracts remain intact.

Acceptance requires focused and affected Odds/ingestion/private/CLI regressions, branch coverage,
static gates, frozen sync, build and installed-wheel smoke, repository and secret validation, safe
live bounded request and transient input compilation using only existing runtime credentials, a
literal one-command retry beyond Odds acquisition, a pushed isolated branch, and exact final-SHA
CI success. No raw provider body, credential, prices, squad or runtime entry ID may be retained.
