# CURRENT-SCORE-PRIOR-001A implementation result

Implementation commit: `3fb675803d7566fe8e24e1310f3ada735afc5e9b`, a direct normal descendant of
architectural parent `7609f041f4f7a415ef58f0f5c682a9b1d5b16d49`.

## Delivered capability

The implementation acquires only four public OpenFootball `football.json` files under immutable
commit `f27dcbef681db2c3195f9def62316ce497278781`: `LICENSE.md` and Premier League seasons 2023/24,
2024/25 and 2025/26. Human-approved rights are checked before the first transport call. Every body
must match its configured byte count, Git blob SHA-1 and raw SHA-256 before parsing.

The strict parser accepts the snapshot's `ht`+`ft`, `ft`-only and Premier-League-scoped direct
reported-score forms without coercion. It requires 380 matches, 20 teams, 38 appearances per team,
380 unique fixture identities and the accepted per-season goal/shape totals. Exact Decimal
`ROUND_HALF_EVEN` arithmetic emits the existing Stage-8 `ScorePriorRequest` orientation:

- `home_goal_rate = 1.613158`
- `away_goal_rate = 1.374561`
- `model_family = INDEPENDENT_POISSON_V1`

## Lineage and boundaries

The full result records the source commit, source timestamp, exact resource identities, receipt
times, validation completion, rights profile/config identities, approval, information cutoff,
usable time, adapter/contract and transport call count. Source mode is `RECONSTRUCTED`; no commit
time is treated as receipt or usable time.

The output is explicitly `WEAK_LEAGUE_LEVEL_SUPPORT_PRIOR`, with `market_evidence_used=false`,
`current_team_strength_claim=false` and `production_active=false`. It performs no database read or
write, no source or derived persistence, no current-market input, no Stage-7 substitution, no score
projection, no player allocation, no Stage 9 and no optimisation.

## Verification

- Exact live snapshot: accepted totals and rates reproduced.
- Focused hostile parser/transport/rights/cutoff suite: 100 passed with branch coverage above 90%.
- Inherited GCS-008/Stage-8 regression: 193 passed.
- PostgreSQL/migration population: 250 passed; disposable state removed.
- Complete repository population: all 3859 collected tests passed across bounded partitions,
  including unmarked database-dependent package, security and availability fixtures.
- Frozen sync, Ruff, strict mypy, build, installed-wheel, repository and secret gates: pass.

`CURRENT_SCORE_PRIOR_001A_IMPLEMENTED_PENDING_INDEPENDENT_REVIEW`

Next action: `INDEPENDENT_REVIEW_CURRENT_SCORE_PRIOR_001A`.

## Independent-review remediation

Reviewed commit `20036f3f7302580bb80ab6ebb9429620db0b8a9b` produced CSP-IR-001 through
CSP-IR-004. Substantive remediation commit `300ea1af1b9e834b011c931391467e9ac7b95aef`
preserves the original estimator, rights decision, selected seasons and immutable source evidence.

- CSP-IR-001: an authenticated `CurrentScorePriorBundle` binds exact fixture, competition,
  home/away team and as-of identities. Conversion rejects substitution or backdating and returns
  the exact nested `ScorePriorRequest` without recomputing rates.
- CSP-IR-002: result, bundle and summary public validation recomputes semantic identity. The
  summary carries both its own hash and its authenticated source-result hash.
- CSP-IR-003: `ScorePriorRequest` is defined in a market-free leaf module and re-exported as the
  identical class from the legacy Stage-8 service path. Frozen GCS schemas and behavior are equal.
- CSP-IR-004: unexpected ordinary transport exceptions become bounded typed failures with exact
  call accounting and no exception-text disclosure; `BaseException` control signals propagate.

Remediation verification: 137 focused tests; 848/885 statements and 186/204 branches; inherited
GCS-008, CURRENT-MARKETS, LIVE-ODDS, CURRENT-FPL-STATE 001B/001D and rights/config populations;
frozen sync, Ruff, strict mypy, build, generic wheel and enhanced installed-wheel proofs.

`CURRENT_SCORE_PRIOR_001A_REMEDIATED_PENDING_INDEPENDENT_REREVIEW`

Next action: `INDEPENDENT_REREVIEW_CURRENT_SCORE_PRIOR_001A`.
