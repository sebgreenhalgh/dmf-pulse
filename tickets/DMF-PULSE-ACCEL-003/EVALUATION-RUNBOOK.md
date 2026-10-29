# Operational player evaluation

The commands use the same `PlayerEvaluationService` as the dashboard report.
They have no provider transport, credential lookup or automatic database write.
Exports contain only authenticated registered owned synthetic data. They fail
closed for arbitrary, resealed, incomplete or unqualified imported inputs.
Existing output files are never overwritten.

After root CLI integration, from an installed wheel outside its source tree:

```powershell
dmf player-lab freeze-owned --output cohort.json
dmf player-lab labels-owned --cohort cohort.json --output labels.json
dmf player-lab score --cohort cohort.json --labels labels.json --output report.json
dmf player-lab demo
dmf player-lab proposal
```

`freeze-owned` authenticates the original registered four-player/two-GW population
and closes all sixteen two-model forecast receipts before opening any actuals
body. `labels-owned` first authenticates that exact forecast export, then reads
the later complete qualified owned labels. `score` authenticates both phases and
original custody, enforces complete joins and chronology, calls inherited
Stage-12 kernels and emits the versioned sealed report. All export paths are
explicit; omission prints owned JSON to stdout. Every import is bounded 4 MB with
duplicate-key rejection, strict fields and semantic authentication. Malformed,
oversize, private, altered or missing inputs return typed exit 2 and no output
artifact. A matching self-computed hash does not confer custody or rights.

The deterministic engineering fixture reports eight targets, zero attrition,
champion MAE/RMSE 2, bias 0,5+ Brier 0.25, RPS 0.25 and central 80% coverage 1. The
component panels use all 13 original point components. Mean-minutes MAE 37.5 and
bias -37.5 come from original forecast minutes versus actual owned per-fixture
counts, not appearance points. Missing start/probability fields stay unavailable.
The holdout contains four chronologically later targets. This is an analytic
oracle, not a genuine prospective cohort, a full current EPL catalogue, evidence
of predictive skill or a complete B0-B5 benchmark evaluation.

The service API accepts `ForecastCohort`, `FinalCohort`, original `CohortCustody`
and an aware monotone evaluation time. It revalidates seals and source rights
before diagnostics. Direct API callers must supply actual original custody;
the public CLI additionally restricts imports to the exact authenticated owned
fixture. The ledger clock simulation is intentionally synthetic. Real issuance
needs its own trusted timestamp/retention authorization, and real source
registry qualification. No configuration flag enables arbitrary real imports.

Model Performance can expose `operational_synthetic_evaluation()` as
`operational_report`, retaining the existing legacy synthetic-report fields.
The same report hash and metrics must match CLI output. The page must continue
showing real cohort 0, unavailable benchmarks/start metrics and forbidden
promotion. It must not attach live transient manager data or silently persist a
live recommendation as a forecast.

Qualified corrections produce a new report with explicit new label hashes while
the original report remains unchanged. Partial/mixed vintages, wrong player,
season/GW/fixture, duplicates, late/resealed forecasts, post-cutoff dependencies
and premature labels are rejected. These are gates, not filters for selectively
scored survivors.
