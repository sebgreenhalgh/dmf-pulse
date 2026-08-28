# CURRENT-MARKETS-001A independent-review remediation

## Chronology

1. Deficient implementation `92f368597c22edbf77b236a8c96ddf959e545f59` was accompanied by
   a same-agent self-review that claimed no unresolved material findings.
2. A fresh independent review reproduced seven defects and returned
   `CURRENT_MARKETS_001A_REMEDIATION_REQUIRED`.
3. Product remediation commit `30ad5c2e821eb03827e16f24d4b22a44ca3804a2` adds the guards and
   direct adversarial regressions described below.
4. Closure is an engineering remediation claim. A fresh independent re-review has not yet
   confirmed any closure.

## Finding record

### CMR-IR-001 — P1 — H2H provider-facing orientation

- Origin: **FOUND BY INDEPENDENT REVIEW**.
- Reproduction: coherently rehashed HOME/AWAY provider-name substitutions were accepted.
- Remediation: each H2H HOME, AWAY and DRAW provider name is checked against the accepted Odds
  event orientation before alias selection or Stage-6 construction; contradictions fail as a
  disclosure-safe `SOURCE_INVALID`.
- Direct regressions: one/all-book swaps, individual HOME/AWAY corruption, DRAW corruption, and
  legitimate ordering permutations.
- Status: **CLOSED BY REMEDIATION `30ad5c2e821eb03827e16f24d4b22a44ca3804a2`**.

### CMR-IR-002 — P1 — unbound Odds temporal state

- Origin: **FOUND BY INDEPENDENT REVIEW**.
- Reproduction: changing local acquisition timestamps could retain a stale request identity.
- Remediation: `current_odds_temporal_sha256()` canonically hashes the complete
  `CurrentOddsTemporalState` and is bound separately into request and lineage.
- Direct regressions: every temporal field, stale-request substitution, fresh rebind, and
  result-identity change where the mutation remains usable.
- Status: **CLOSED BY REMEDIATION `30ad5c2e821eb03827e16f24d4b22a44ca3804a2`**.

### CMR-IR-003 — P1 — totals receipt-time coherence

- Origin: **FOUND BY INDEPENDENT REVIEW**.
- Reproduction: totals observations later than the accepted response receipt could enter a
  result when still no later than market `as_of`.
- Remediation: market and bookmaker-fallback observations later than `received_at` are excluded
  as `FUTURE_OBSERVATION` before canonical-operator alias ranking.
- Direct regressions: before/equal/after receipt for both timestamp sources, valid older alias
  retention, and all-future alias exclusion.
- Status: **CLOSED BY REMEDIATION `30ad5c2e821eb03827e16f24d4b22a44ca3804a2`**.

### CMR-IR-004 — P1 — unapproved mapping authority

- Origin: **FOUND BY INDEPENDENT REVIEW**.
- Reproduction: all `AUTO_MATCHED` rows were accepted without an explicit immutable approval
  contract for method, confidence and evidence.
- Remediation: every blocking official-FPL fixture, Odds fixture and betting-operator mapping now
  requires `HUMAN_VERIFIED`.
- Direct regressions: HUMAN_VERIFIED positive; probabilistic/high/low/zero/null AUTO_MATCHED and
  CANDIDATE, UNRESOLVED, CONFLICTED, REJECTED and EXPIRED negatives.
- Status: **CLOSED BY REMEDIATION `30ad5c2e821eb03827e16f24d4b22a44ca3804a2`**.

### CMR-IR-005 — material P2 — incomplete official-FPL fixture scope

- Origin: **FOUND BY INDEPENDENT REVIEW**.
- Reproduction: official-FPL resolution did not constrain provider product, active provider or
  canonical competition.
- Remediation: the query joins canonical competition and requires active `official_fpl`, product
  `fantasy_premierleague`, competition `PL`, exact source season, exact namespace/entity type,
  applicability/system ranges and HUMAN_VERIFIED authority.
- Direct regressions: wrong product, inactive provider, wrong/cross competition, wrong season,
  namespace/entity/ranges and ambiguous authority.
- Status: **CLOSED BY REMEDIATION `30ad5c2e821eb03827e16f24d4b22a44ca3804a2`**.

### CMR-IR-006 — material P2 — unauthenticated Odds rights identity

- Origin: **FOUND BY INDEPENDENT REVIEW**.
- Reproduction: changing nested rights profile ID/version could preserve request/result identity.
- Remediation: the exact HUMAN_APPROVED `the_odds_api_private_analytics_v1` version `1.0.0`
  profile is authenticated from the packaged registry; supplied and packaged config hashes must
  match. `current_odds_rights_sha256()` binds the complete source rights state and exact accepted
  authority into request and lineage.
- Direct regressions: wrong ID/version/config, provider/status authority mismatch and effective
  capability denial, including safe serialized errors.
- Status: **CLOSED BY REMEDIATION `30ad5c2e821eb03827e16f24d4b22a44ca3804a2`**.

### CMR-IR-007 — material P2 — test/evidence quality

- Origin: **FOUND BY INDEPENDENT REVIEW**.
- Reproduction: the historical same-agent evidence claimed boundaries closed despite reproduced
  failures, while raw branch coverage was approximately 85.135%.
- Remediation: this chronology corrects the record; direct tests cover every finding and critical
  binary-normalizer, timestamp, alias and repository failure path. Focused coverage is 781/804
  statements (97.13930348258707%), 215/232 branches (92.67241379310344%), and 96.13899613899613%
  combined.
- Status: **CLOSED BY REMEDIATION `30ad5c2e821eb03827e16f24d4b22a44ca3804a2`**.

## Engineering finding accounting

- P0 historical/unresolved: 0 / 0.
- P1 historical/closed/unresolved: 4 / 4 / 0.
- Material P2 historical/closed/unresolved: 3 / 3 / 0.
- P3 unresolved: 0.

Status: `CURRENT_MARKETS_001A_REMEDIATED_PENDING_INDEPENDENT_REREVIEW`.

Next action: `INDEPENDENT_REREVIEW_CURRENT_MARKETS_001A`.
