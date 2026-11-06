# Forecast validation scorecard

As of 2026-11-07, the permitted local analytical inventory has no matched final
outcome labels or frozen benchmark forecasts with which to calculate genuine
predictive scores. The private audit authenticates the original GW10 view against
the existing pinned export/terminal review; it does not run a historical model.
No provider, production PostgreSQL query, or research-registry mutation occurred.
This establishes an inventory limit, not a claim that no other archive exists.

| Target | Genuinely evaluable sample here | Result | Benchmark and uncertainty required |
| --- | --- | --- | --- |
| Player points mean/median | 0 matched finalized forecast/label pairs | MAE, RMSE, bias unavailable | Same population/cutoff B0 recent points, B1 official form, B2 market, B3 market+minutes, B4 champion; distinguish mean from median targets; paired GW-block intervals. |
| Starts | 0 finalized pairs | Brier, log score and calibration unavailable | Frozen player p_start vs official starts, including zero-minute starters; intercept/slope and reliability with uncertainty. |
| Minutes | 0 finalized pairs | MAE/RMSE, zero/60+ calibration unavailable | Unconditional PMF and start/bench-conditional distributions; distinct hard-out, regular, sparse-history, new-transfer and DGW cohorts. |
| Goals/assists/CS/bonus/defence | 0 finalized pairs | Component/probability scores unavailable | Exact rules/finality, proper scores and component reconciliation; goals vs nonpenalty goals and football vs FPL assists distinct. |
| Full point distributions | 0 finalized pairs | CRPS/RPS/log score, PIT and coverage unavailable | Retained complete PMFs; common support and declared scoring convention; 80% central interval width and coverage; joint energy/variogram scores if rights permit derived sufficient evidence. |
| Rankings | 0 successive evaluable frozen vintages | Rank stability/skill unavailable | Same eligible universe, rank correlation with ties and uncertainty, turnover near transfer boundary. |
| Squad/transfer/chips/rank policy | 0 complete prospective sequences | Regret or season policy skill unavailable | Sequential root-action replay, actual manager/price/FT/chip state transitions, paired policy uncertainty and feasible comparators. |

No confidence interval or significance can be estimated from an empty evaluation
sample. Player rows from one GW are dependent and cannot substitute for multiple
independent deadlines. A successful engineering replay or a Monte Carlo PASS
does not fill any cell in this scorecard.

## Existing machinery to connect

`evaluation/service.py:EvaluationService` already exposes chronological folds,
cutoff-filtered information sets, B0-B5 benchmark definitions, sealed forecasts
and labels, point/distribution/calibration metrics and reports. Its `policy`
path uses `SyntheticReplayPolicy`/`SyntheticReplayExecutor`; it is not evidence
of accepted current-football policy performance. `point_metrics.py` distinguishes
target functionals and checks sealed alignment/finality. Distribution and joint
metrics, leakage canaries and paired/block uncertainty tooling exist in the
same package. Tests under `tests/unit/evaluation`, `tests/integration/evaluation`
and `fixtures/historical` protect these engineering contracts.

The more specific `player_lab/real.py` and `real_store.py` already implement
qualified real protocol/deadline/population registration, fixed model bindings,
predeadline forecast freezing, finalized label append and stored scoring.
`RealPlayerProtocol` separates PREREGISTERED_PROSPECTIVE from
POST_ORIGIN_DESCRIPTIVE, earlier inner folds from locked later holdouts,
full all-player coverage and GW-cluster uncertainty. `real_rights.py` requires
purpose-specific qualified sources; the operational registry is not populated
merely by recommendation permission. `adapt_qualified_full_forecast` and
`freeze_forecast` should be integrated, not reimplemented. Team-score P01
prospective protocol and its consumed/failed observations remain immutable and
separate from current player validation.

## Prospective collection contract

1. Before the first new target deadline, register the exact protocol, model/rules/
   configuration/source bindings, full population, benchmark definitions,
   chronological selection/holdout periods and metric policy. Acquire no data
   until exact route, research/label retention purpose and zero/explicit budget
   have separate qualified authority.
2. Freeze existing completed champion/challenger/benchmark outputs before the
   deadline through the existing PostgreSQL research service. Capture the actual
   information-use and publication times, source usable_at and source hashes.
   An after-deadline warehouse import is not a predeadline freeze certificate.
3. Append only permitted finalized outcome fields with stable season/player/
   fixture/GW identities, actual label available/finalized times and revision ID.
   Partial/missing labels stay missing; preserve earlier vintages and revisions.
4. Run existing metrics on complete aligned populations; report denominators,
   unavailable benchmarks and cohorts by team/fixture/position/price/minutes/
   season phase. Derive read-only analytical evaluation views from authenticated
   scorecards; SQLite must not become the research authority.
5. Compare challengers on the same frozen sample with paired GW-block intervals,
   predeclared practical improvement and calibration constraints. Keep failures
   and neutral findings in the experiment register. Do not select on the holdout.

Minimum sample size, promotion effect and safety thresholds require a concrete
preregistered protocol and authority; this audit invents none. Grade E is
justified by stale candidate allocation and absent qualifying validation. An
upgrade needs current permitted evidence, cohort coverage, out-of-time/prospective
proper-score and decision checks plus independent review and owner acceptance;
changing a label or adding a table cannot upgrade confidence.
