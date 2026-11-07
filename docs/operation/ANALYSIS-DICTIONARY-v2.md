# Private analysis warehouse: research schema v2 supplement

`ANALYSIS-DICTIONARY-v1.md` is preserved byte-for-byte. This supplement describes
additive derived views prepared on `research/DMF-MODEL-QUALITY-001`. The canonical
live warehouse remains v1 and unchanged. New reader code reads v1 and v2; its
explicit `initialize()` migrates a research copy to v2. `analysis query`,
`analysis export` and `analysis quality` never call initialize or migrate.

## Definitions, identities and types

All rows below come only from confirmed snapshots through the unchanged `runs`
digest join. `run_id TEXT` and `snapshot_sha256 TEXT` identify the exact immutable
payload. `official_id INTEGER` is an official FPL player ID **within the run's
season**, not a globally stable cross-season identifier. `player_id TEXT` is its
canonical ID. `gameweek INTEGER` is the projection GW. Join runs before comparing
seasons; the preexisting v1 `run_player_changes` view is not a validated
cross-season player-identity join. It is left unchanged for historical compatibility.

| View / grain | Additional columns and SQL types | Exact definition / null semantics |
| --- | --- | --- |
| `player_gameweek_metrics_v2` / run, GW, player | `projection_sha256 TEXT`, `ruleset_hash TEXT`; `expected_points REAL`; `probability_zero_points REAL`; `effective_sample_size REAL`; `mean_se REAL`; `points_pmf_json TEXT`, `components_json TEXT`, `bonus_json TEXT`, `probability_se_json TEXT`, `derived_json TEXT` | Exact fields from retained `presentation.gameweeks[].summaries[player_id]`. xPts = sum of integer point support times probability. Zero-point probability is not nonappearance probability. MC SE/ESS describe numerical sampling, not model uncertainty. No retained Gameweek object means **no detail row**, not a fabricated all-zero forecast. |
| `player_fixture_metrics_v2` / run, official fixture, player | `official_fixture_id INTEGER`, `fixture_id TEXT`, `projection_sha256 TEXT`, `ruleset_hash TEXT`; `expected_points REAL`, `probability_zero_points REAL`; `components_json TEXT`, `points_pmf_json TEXT`; `p_start TEXT`, `p_zero_minutes TEXT`, `expected_minutes TEXT`, `minute_pmf_json TEXT`, `minutes_confidence_reasons_json TEXT` | Point summary from exact fixture; minutes from its matching canonical player key. Probabilities/minutes preserve original decimal strings. PMF bins index minutes 0..90. Missing minute object => SQL NULL in minute fields, while retained point fields remain available. No fixture object => no fixture row. Never infer team membership from a familiar name. |
| `player_component_metrics_v2` / run, scope, GW, optional fixture, player, component | `metric_scope TEXT` = GAMEWEEK or FIXTURE; `official_fixture_id INTEGER` null for GAMEWEEK; `component TEXT`; `expected_points REAL`, `probability_nonzero REAL`, `variance REAL` | Exact component breakdown fields. Component means reconcile to point mean. Component variances cannot be summed as total variance without covariance. Fixture and GW rows overlap; filter scope before aggregation. Missing objects produce no component rows. |

JSON text fields contain derived summaries/PMFs, not source bodies or source
scenario matrices. Component probability refers to nonzero **point contribution**,
not necessarily the underlying event occurring. REAL values preserve existing
binary numerical outputs; original JSON remains the exact historical source.

The normalized official-player mapping is materialized once per SQL statement
to avoid rescanning a large forecast JSON object for every projection row. New
writes and v1-to-v2 migration reject ambiguous canonical player IDs, duplicate
Gameweek/fixture identities and mismatched fixture summary/minute keys. Migration
also checks each existing snapshot's semantic digest. Invalid v1 history remains
readable using v1 diagnostics; a refused migration never repairs it silently.

## Offline quality command

```
dmf analysis quality --database PRIVATE_COPY --run-id RUN_ID
```

It prints `analysis-quality-v1` / `retained-derived-diagnostics-v1` private derived
JSON. It is pure after the existing read-only snapshot load: no forecasts,
credentials, providers, reservations, storage writes or outcome fetches.
The report carries the unchanged source provenance class, explicit permission
origin and private derived retention restriction alongside the snapshot hash.

- Counts distinguish missing point forecasts from zero/nonzero forecasts,
  missing minutes and positive minutes. Retained exact all-zero minute PMF can
  confirm modeled zero-minute mass, but cannot prove actual nonparticipation.
  Without the PMF the cause stays unavailable.
- Displayed expected minutes round to six decimals. A zero-display/nonzero-xPts
  flag is an observational inconsistency to investigate; tiny positive exposure
  could round to zero. Invalid probability bounds/strings, negative retained
  uncertainty, malformed PMF masses/mean/normalization, nonmonotone quantiles
  and identity ambiguities are reported without changing the original data.
- `team.starting_xi_expected_points` sums retained XI marginal means;
  `captain_standalone_expected_points` is one extra standalone captain copy;
  `xi_plus_standalone_captain` is their sum. `retained_before_hit` and
  `retained_after_hit` copy the actual paired-comparison result.
  `unattributed_difference = retained_before_hit - xi_plus_standalone_captain`.
  This is an arithmetic residual, **not** the autosub contribution. Joint autosub,
  vice-contingency and captain-only counterfactual terms remain null. Incomplete
  marginals and rolling team accounting have explicit unavailable statuses.
- `maximum_retained_mean_se` is the largest available player mean SE; missing
  input stays null. Exact MC policy and predictive performance remain null when
  not retained. `validation` remains UNVALIDATED. No grade is upgraded.

## Migration and deployment

`AnalysisStore.initialize()` keeps v1 tables, triggers, views, records and hashes
unchanged, then installs the three additive views in one `BEGIN IMMEDIATE`
transaction and advances user_version to 2. Failure rolls back all v2 DDL and
the version together; repeat initialization is idempotent. No reset, history
rewrite, provider call, or research-authority mutation occurs.

The current signed v1 wheel cannot read a migrated user_version=2 database.
Production activation therefore requires a separate reviewed rollback-compatible
release/migration plan and owner acceptance. Only owned databases and research
copies are migrated in this programme. Do not point initialize at the live path.

The existing read query limits remain 10,000 rows, 16 MiB, 16 KiB SQL and five
seconds. A full two-scope component expansion can exceed the row cap. Filter by
run/GW/scope or aggregate in SQL, for example:

```sql
SELECT official_id,gameweek,SUM(expected_points) AS expected_points
FROM player_component_metrics_v2
WHERE run_id='OWNED_RUN' AND metric_scope='GAMEWEEK'
GROUP BY official_id,gameweek;
```

## Subsequent metrics requiring qualified inputs

Future additions must bind to existing versioned derived outputs rather than
store arbitrary JSON blobs. Proposed fields are not populated by this migration:

| Future metric | Definition / type / missingness | Required lineage |
| --- | --- | --- |
| Cumulative horizon points | REAL mean by explicit start/end GW; interval/PMF and dependence-mode TEXT; null for unsupported horizons | Each per-GW projection hash, joint-path/dependence policy and scenario/parameter version; never fabricate 5/8-GW uncertainty by summing independent intervals. |
| Player evidence | INTEGER usable rows/exposure minutes/events where lawful; prior weight REAL, fallback level/reason TEXT, nullable observed fields | Exact channel/source cutoff and model/parameter provenance; individual historical channel is not fully individualized xPts. |
| Captaincy | Ordered captain/vice IDs, fixed tactic hash, REAL effective bonus/paired delta/SE, derived PMF TEXT and resolution frequencies | Existing evaluator, common joint scenario/rules hashes; absent historical counterfactual stays null. |
| Transfer/chip policies | Legal route IDs, scope/status, REAL paired expected net gain, cost/opportunity terms, derived paired PMF | Existing Stage-11/14 result/hash and manager/rules/token/continuation lineage; best supplied route distinct from global optimum. |
| Forecast evaluation | INTEGER n, target/cohort/horizon/benchmark IDs, REAL metric and bounds; unavailable metrics null | Existing real research protocol, predeadline freeze and finalized label/scorecard digests; SQLite holds a derived read model, not custody authority. |
| Rank/price | Explicit target, cohort or price-update horizon, REAL probability/utility and uncertainty, status TEXT | Existing accepted Stage-13/15 evidence, source rights, exact observation/finality/cutoff and activation status; no unsupported live hazard/rank point estimate. |

No GrowthOS logic, training dataset, restricted raw provider body or credential
is included in this schema or its proposed successors.
