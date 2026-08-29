# CURRENT-MARKETS-001A independent-review remediation

## Chronology

1. Deficient implementation `92f368597c22edbf77b236a8c96ddf959e545f59` was accompanied by
   a same-agent self-review that claimed no unresolved material findings.
2. A fresh independent review reproduced seven defects and returned
   `CURRENT_MARKETS_001A_REMEDIATION_REQUIRED`.
3. Product remediation commit `30ad5c2e821eb03827e16f24d4b22a44ca3804a2` adds the guards and
   direct adversarial regressions described below.
4. Governance continuation `f58790c4d2d3ed56a472bd3d52583451dbebab6c` was the unit inspected
   by an interrupted independent re-review. That re-review independently closed
   CMR-IR-001/002/004/005/006, kept CMR-IR-003/007 open, and found CMR-IR-008/009.
5. Second-remediation product commit `562e5a586881d9e462075ffd5dad01401b265ff3`
   closes the four current findings by engineering. Fresh independent re-review has not yet
   confirmed those closures.
6. Final independent re-review inspected governance continuation
   `ee4a35760a56f84b4f0f50f3d2f898e2037d105a`. It independently closed
   CMR-IR-002/003/004/005/006/007/009, found CMR-IR-010 (P1), found CMR-IR-011
   (material P2), and treated CMR-IR-001/008 as open only through the CMR-IR-010 regression.
7. Third-remediation product/tests commit `316d52b87f113f9364ee0dab9c296cf8fe0ff544`
   closes CMR-IR-010/011 by engineering and restores the CMR-IR-001/008 regression. Fresh
   independent closure remains pending.

## Finding record

### CMR-IR-001 — P1 — H2H provider-facing orientation

- Origin: **FOUND BY INDEPENDENT REVIEW**.
- Reproduction: coherently rehashed HOME/AWAY provider-name substitutions were accepted.
- Remediation: each H2H HOME, AWAY and DRAW provider name is checked against the accepted Odds
  event orientation before alias selection or Stage-6 construction; contradictions fail as a
  disclosure-safe `SOURCE_INVALID`.
- Direct regressions: one/all-book swaps, individual HOME/AWAY corruption, DRAW corruption, and
  legitimate ordering permutations.
- Status: **CLOSED; CONFIRMED BY INTERRUPTED INDEPENDENT RE-REVIEW**.
- Final-re-review effect: **ENGINEERING_RESTORED_AT_316d52b87f113f9364ee0dab9c296cf8fe0ff544;
  INDEPENDENT CLOSURE PENDING THROUGH CMR-IR-010**.

### CMR-IR-002 — P1 — unbound Odds temporal state

- Origin: **FOUND BY INDEPENDENT REVIEW**.
- Reproduction: changing local acquisition timestamps could retain a stale request identity.
- Remediation: `current_odds_temporal_sha256()` canonically hashes the complete
  `CurrentOddsTemporalState` and is bound separately into request and lineage.
- Direct regressions: every temporal field, stale-request substitution, fresh rebind, and
  result-identity change where the mutation remains usable.
- Status: **CLOSED; CONFIRMED BY INTERRUPTED INDEPENDENT RE-REVIEW**.

### CMR-IR-003 — P1 — receipt-time alias selection

- Origin: **FOUND BY INDEPENDENT REVIEW**.
- Reproduction: totals observations later than the accepted response receipt could enter a
  result when still no later than market `as_of`.
- First remediation: totals market and bookmaker-fallback observations later than `received_at`
  were excluded before canonical-operator alias ranking. The interrupted independent re-review
  found that H2H still ranked aliases before applying the receipt boundary.
- Second remediation: every H2H alias now derives its market or truthful bookmaker-fallback
  observation time and excludes post-receipt evidence before canonical grouping or ranking.
- Committed regressions: invalid-newer/valid-older, all-future, newest-valid, tied-identical,
  tied-conflict, bookmaker fallback, receipt-before-market-as-of, and ordering permutations.
- Status: **ENGINEERING_CLOSED_AT_562e5a586881d9e462075ffd5dad01401b265ff3;
  INDEPENDENT CLOSURE PENDING**.
- Final-re-review disposition: **CLOSED; CONFIRMED BY FINAL INDEPENDENT RE-REVIEW**.

### CMR-IR-004 — P1 — unapproved mapping authority

- Origin: **FOUND BY INDEPENDENT REVIEW**.
- Reproduction: all `AUTO_MATCHED` rows were accepted without an explicit immutable approval
  contract for method, confidence and evidence.
- Remediation: every blocking official-FPL fixture, Odds fixture and betting-operator mapping now
  requires `HUMAN_VERIFIED`.
- Direct regressions: HUMAN_VERIFIED positive; probabilistic/high/low/zero/null AUTO_MATCHED and
  CANDIDATE, UNRESOLVED, CONFLICTED, REJECTED and EXPIRED negatives.
- Status: **CLOSED; CONFIRMED BY INTERRUPTED INDEPENDENT RE-REVIEW**.

### CMR-IR-005 — material P2 — incomplete official-FPL fixture scope

- Origin: **FOUND BY INDEPENDENT REVIEW**.
- Reproduction: official-FPL resolution did not constrain provider product, active provider or
  canonical competition.
- Remediation: the query joins canonical competition and requires active `official_fpl`, product
  `fantasy_premierleague`, competition `PL`, exact source season, exact namespace/entity type,
  applicability/system ranges and HUMAN_VERIFIED authority.
- Direct regressions: wrong product, inactive provider, wrong/cross competition, wrong season,
  namespace/entity/ranges and ambiguous authority.
- Status: **CLOSED; CONFIRMED BY INTERRUPTED INDEPENDENT RE-REVIEW**.

### CMR-IR-006 — material P2 — unauthenticated Odds rights identity

- Origin: **FOUND BY INDEPENDENT REVIEW**.
- Reproduction: changing nested rights profile ID/version could preserve request/result identity.
- Remediation: the exact HUMAN_APPROVED `the_odds_api_private_analytics_v1` version `1.0.0`
  profile is authenticated from the packaged registry; supplied and packaged config hashes must
  match. `current_odds_rights_sha256()` binds the complete source rights state and exact accepted
  authority into request and lineage.
- Direct regressions: wrong ID/version/config, provider/status authority mismatch and effective
  capability denial, including safe serialized errors.
- Status: **CLOSED; CONFIRMED BY INTERRUPTED INDEPENDENT RE-REVIEW**.

### CMR-IR-007 — material P2 — test/evidence quality

- Origin: **FOUND BY INDEPENDENT REVIEW**.
- Reproduction: first-remediation evidence claimed pending/dirty SQLAlchemy Session coverage that
  did not exist in the committed suite. Reviewer-only exploratory probes did observe read-only
  behavior, but those probes were not committed engineering evidence.
- Second remediation: committed tests
  `test_cmr_ir_007_pending_orm_state_is_not_autoflushed_by_resolver_selects` and
  `test_cmr_ir_007_dirty_orm_state_is_not_autoflushed_by_resolver_selects` use PostgreSQL and
  `autoflush=True`, retain pending/dirty ORM state, observe zero flush/DML, compare canonical,
  mapping, operator and market-result row counts, and roll back.
- Coverage: 818/841 statements (97.26516052318668%) and 230/248 branches
  (92.74193548387096%); both figures are reported separately.
- Status: **ENGINEERING_CLOSED_AT_562e5a586881d9e462075ffd5dad01401b265ff3;
  INDEPENDENT CLOSURE PENDING**.
- Final-re-review disposition: **CLOSED; CONFIRMED BY FINAL INDEPENDENT RE-REVIEW**.

### CMR-IR-008 — P1 — cross-source orientation

- Origin: **FOUND BY INTERRUPTED INDEPENDENT RE-REVIEW**.
- Reproduction: a coherently swapped and rehashed current Odds event plus matching H2H labels was
  accepted while the accepted 001B identity map remained unchanged.
- Remediation: `build()` recomputes the current provider-event identity and exact event fields,
  reconstructs both accepted 001B team mappings, and checks the official FPL fixture home/away
  identities and kickoff before any H2H or totals use. The local H2H label guard remains.
- Committed regressions: coherent full swap, participant-only swap, label-only swap, sealed map
  mutation, official-FPL orientation mutation, exact home/away team-bridge mismatch, verify-path
  reconstruction, ordering, and installed-wheel reproduction.
- Status: **ENGINEERING_CLOSED_AT_562e5a586881d9e462075ffd5dad01401b265ff3;
  INDEPENDENT CLOSURE PENDING**.
- Final-re-review effect: **ENGINEERING_RESTORED_AT_316d52b87f113f9364ee0dab9c296cf8fe0ff544;
  INDEPENDENT CLOSURE PENDING THROUGH CMR-IR-010**.

### CMR-IR-009 — material P2 — operator validity at every occurrence

- Origin: **FOUND BY INTERRUPTED INDEPENDENT RE-REVIEW**.
- Reproduction: one bookmaker occurring at 14:00 and 16:00 was resolved from a mapping valid only
  at the minimum occurrence.
- Remediation: target-only occurrence times are collected as sorted unique tuples. One exact
  HUMAN_VERIFIED mapping row must contain every timestamp; mappings are never combined. A
  disclosure-safe occurrence digest is embedded in and reconstructed against the identity view.
- Committed PostgreSQL regressions: ranges covering both, expiring before the second, starting
  after the first, inclusive lower, excluded upper, bookmaker absent from the later fixture,
  unrelated outside-target event, and DAT-003 duplicate-current-authority blocking.
- Status: **ENGINEERING_CLOSED_AT_562e5a586881d9e462075ffd5dad01401b265ff3;
  INDEPENDENT CLOSURE PENDING**.
- Final-re-review disposition: **CLOSED; CONFIRMED BY FINAL INDEPENDENT RE-REVIEW**.

### CMR-IR-010 — P1 — post-receipt H2H label-validation bypass

- Origin: **FOUND BY FINAL INDEPENDENT RE-REVIEW**.
- Reproduction: a freshly rehashed future H2H alias with a malformed HOME, AWAY or DRAW provider
  label reached the receipt-time `continue` before the local orientation guard.
- Remediation: all three supplied H2H outcomes are structurally/orientationally validated before
  canonical-operator lookup, timestamp derivation, receipt-time exclusion or alias ranking.
- Direct regressions: HOME/AWAY/DRAW, one/all aliases, market/bookmaker timestamp source, forward
  and reversed ordering, valid-future/valid-older retention, all-valid-future exclusion,
  disclosure-safe surfaces, and installed-wheel reproduction.
- Status: **ENGINEERING_CLOSED_AT_316d52b87f113f9364ee0dab9c296cf8fe0ff544;
  INDEPENDENT CLOSURE PENDING**.

### CMR-IR-011 — material P2 — totals-market semantic tuple ordering

- Origin: **FOUND BY FINAL INDEPENDENT RE-REVIEW**.
- Classification: **CONTROLLED UPSTREAM LIVE-ODDS SEMANTIC-CANONICALIZATION CORRECTION**; not a
  rewrite of the historical accepted LIVE-ODDS capability.
- Reproduction: valid multi-line `CurrentOddsBookmaker.totals_markets` objects with identical
  content in reversed tuple order produced different supported-market semantic hashes.
- Remediation: only `_current_odds_market_semantic_payload()` sorts totals-market projections by
  exact Decimal line. H2H remains first; stored tuple order, builder selection, schema/version,
  prices, normalization, rights, temporal, quota, identity and persistence are unchanged.
- Direct regressions: two-line reversal, all three-line permutations, OVER/UNDER reversal,
  bookmaker/event order, line-set/price mutations, 001D unified identity, CURRENT-MARKETS
  request/result/summary and installed-wheel reproduction.
- Normal builder impact: unchanged semantic SHA-256
  `27880ba63a4555ee74f21b8c5acdeccc73c7194d57b8ea663bef8fed4cc44abf` before and after.
- Status: **ENGINEERING_CLOSED_AT_316d52b87f113f9364ee0dab9c296cf8fe0ff544;
  INDEPENDENT CLOSURE PENDING**.

## Engineering finding accounting

- P0 historical/unresolved: 0 / 0.
- P1 historical: 6. Independently closed: CMR-IR-002/003/004. Engineering-restored or closed
  pending independent confirmation: CMR-IR-001/008/010. Engineering-unresolved: 0.
- Material P2 historical: 5. Independently closed: CMR-IR-005/006/007/009. Engineering-closed
  pending independent confirmation: CMR-IR-011. Engineering-unresolved: 0.
- P3 unresolved: 0.

CMR-IR-002/003/004/005/006/007/009 retain their final independent closed disposition.
CMR-IR-001/008 are engineering-restored through CMR-IR-010; CMR-IR-010/011 are engineering
closed. Fresh independent confirmation is still required.

Status: `CURRENT_MARKETS_001A_REMEDIATED_PENDING_INDEPENDENT_REREVIEW`.

Next action: `INDEPENDENT_REREVIEW_CURRENT_MARKETS_001A`.
