# PRIVATE-V1-ONE-COMMAND-001N-R3 acceptance

The entry endpoint alone may retain top-level duplicate occurrences for the four documented
summary keys. Duplicate `id`, `started_event`, unknown top-level keys and every nested key fail
closed. Equal points duplicates are accepted; conflicting points duplicates fail. Conflicting
overall rank is retained only when the strict canonical history row for `target_gameweek - 1`
matches unambiguous total points and exactly one candidate rank; otherwise rank is `None` with
typed provenance. Other endpoints retain their strict duplicate behaviour. No raw provider body
or secret may be retained. Quality warnings must reach sealed one- and three-GW decisions.
