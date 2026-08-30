# CURRENT-SCORE-PRIOR-001A implementation result

Implementation commit: `3fb67585e48577f9036fef34b87ec27d63e0b2d4`, a direct normal descendant of
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
