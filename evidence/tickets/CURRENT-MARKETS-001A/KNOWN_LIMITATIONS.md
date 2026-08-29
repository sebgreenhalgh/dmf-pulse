# CURRENT-MARKETS-001A known limitations

- CURRENT-AVAILABILITY-001A remains data-blocked by accepted history evidence. This capability
  does not produce availability or live minutes.
- No accepted current score-support prior exists at the pinned parent. The exact downstream
  blocker is `NO_ACCEPTED_CURRENT_SCORE_PRIOR`.
- No `Stage7MinutesContext` is fabricated and the full GCS-008 live service is not executed.
- Market constraints and all source-derived market evidence are private, transient in memory and
  non-persistent.
- Totals support is limited to complete full-time over/under pairs at exact nonnegative half-goal
  lines already represented in the accepted 001D Odds input.
- No provider acquisition, authentication, market scraping, raw storage, derived storage, cache,
  backup, public display or redistribution is authorized or implemented.
- No availability model, score-rate inference, score distribution, player-event allocation, FPL
  points, squad/transfer/lineup/captaincy/chip/rank optimisation, Decision Bundle or production
  activation is implemented.
- Canonical identity resolution requires existing accepted DAT-003 rows. It never creates missing
  fixtures, providers, operators or external mappings. Blocking current-market fixture and
  operator mappings must be HUMAN_VERIFIED; no AUTO_MATCHED approval path is claimed.
- CMR-IR-001/002/004/005/006 are independently closed. CMR-IR-003/007/008/009 are
  engineering-remediated at `562e5a586881d9e462075ffd5dad01401b265ff3` but await fresh
  independent re-review. Deficient and first-remediation chronology remains in Git.
- The result is not human-accepted or production-approved. Every later commit requires separate
  review as applicable.
