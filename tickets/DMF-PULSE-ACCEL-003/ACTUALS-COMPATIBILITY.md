# Actuals compatibility proposal v2

This version describes an offline candidate contract. It does not change the
accepted strict v1 adapter, qualify its JSON as observed live, add an FPL route
or permit retained real labels. A structural compatibility result always reports
`observed_live_schema=false` and `retention_authorized=false`.

The current official 2026/27 textual update establishes next-day 09:00 UK points
lock, provisional live bonus, post-match reviews and rare extraordinary
corrections. The official scoring explanation describes the 13 point categories,
minutes excluding stoppage time and the 60-minute boundary. Defensive-contribution
points are capped per fixture. These primary textual sources were inspected
through indexed official HTML, not provider JSON:

- [Official2026/27 updates](https://fantasy.premierleague.com/help/new)
- [Official scoring explanation,20 July 2026](https://www.premierleague.com/en/news/2174909/)
- [Official defensive contributions explanation](https://www.premierleague.com/en/news/4361991)

Direct help-page opens returned no extracted lines. The indexed sources support
the named conventions; they do not establish the endpoint schema. Older official
FAQ article 4661030 still describes the earlier one-hour update/finality timing.
The newer target-season update controls; do not regress the current finality.

Unknowns requiring a separately authorized exact schema observation include:

- Exact fields/types, additional stats and defensive-contribution spelling.
- Whether 13 zero-valued explain categories are sparse or explicit.
- Blank/double-GW explain encoding and possible fixture-count limits.
- Independent actual start labels and continuity after club transfers.
- Authoritative checked/final markers and correction publication.

The current candidate requires 13 explicit stats per fixture, no unknown fields,
exact all-player and fixture bijections, count/point-total reconciliation and
explicit finality context. Sparse fields remain blocked; absent is not zero.
No generic provider football goal/assist labels can replace FPL-specific assists,
bonus or final point components. A source must independently qualify both its
raw payload/context and each output label before the research runner uses it.

New tests exercise sparse/extra/changed/duplicate fields, booleans, partial
finality, explicit blank and double GWs, canonical transferred-player identity,
fixture mismatch and London daylight-saving lock boundaries. They demonstrate
offline contract behavior, not live source compatibility. Original/corrected GW
vintages are separately authenticated; one report rejects mixed revisions.

The minutes diagnostic sidecar reads exact original count values and binds the
outcome/source hashes. It never reconstructs starts from minutes or points.
Missing start labels and frozen probabilities are reported unavailable. The
research database's synthetic-only source qualification and forbidden-write
gates remain unchanged.
