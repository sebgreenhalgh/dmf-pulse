# PRIVATE-V1-ONE-COMMAND-001E engineering acceptance

The authenticated provider may publish one current record per FPL chip while the governed rules
mint multiple seasonal tokens. A played record maps to the unique governed activation window that
contains its played Gameweek. A current unplayed record maps to the unique governed token whose
activation window contains the target Gameweek. Provider copy numbers are not global seasonal
token indexes.

Every governed token still produces a declaration. Provider-bound tokens incorporate the strict
known provider status and played history; an unpublished future token retains its rules-derived
base status. The adapter fails closed for unknown chip identities or statuses, incomplete current
chip types, duplicate or unreconcilable records, multiple records mapping one token, played events
outside or in multiple windows, disallowed multi-event histories, contradictory status/history,
and absence of a unique current token.

Acceptance requires focused GW3 and GW20 mapping regressions, played first-window and future-token
proofs, inherited manual/current inventory compatibility, affected ingestion/private tests,
branch coverage and static gates, frozen sync, build and installed-wheel smoke, repository and
secret validation, a safe authenticated snapshot and one-command retry using only the existing
runtime bearer environment mechanism, a pushed isolated branch, and exact final-SHA CI success.
No credential, provider body, squad, prices, or runtime entry identifier may be retained.
