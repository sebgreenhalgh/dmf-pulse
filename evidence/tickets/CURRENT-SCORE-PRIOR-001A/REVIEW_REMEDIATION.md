# CURRENT-SCORE-PRIOR-001A independent-review remediation

Reviewed commit: `20036f3f7302580bb80ab6ebb9429620db0b8a9b`

Substantive remediation: `300ea1af1b9e834b011c931391467e9ac7b95aef`

The original reviewed commit and findings remain immutable history. These are engineering
dispositions only and require a fresh independent re-review.

## CSP-IR-001 — fixture, competition and provenance binding

Disposition: `ENGINEERING_CLOSED_PENDING_INDEPENDENT_REREVIEW`

`CurrentScorePriorBundle` authenticates the exact fixture, competition, oriented home/away teams,
as-of time, source result/hash, usable time, source mode, method/model and exact nested request.
The supported converter requires exact downstream equality, blocks an earlier as-of decision and
returns the nested request object without rate reconstruction.

## CSP-IR-002 — semantic SHA authentication

Disposition: `ENGINEERING_CLOSED_PENDING_INDEPENDENT_REREVIEW`

`CurrentScorePriorResult`, `CurrentScorePriorBundle` and `CurrentScorePriorSummary` recompute their
own canonical SHA during public validation and JSON deserialization. Construction validates the
semantic body before computing the final hash. The summary separately records its authenticated
source-result SHA. Rate, total, source, rights, mode, time, binding and nested-source mutations with
a stale or arbitrary hash reject.

## CSP-IR-003 — market import coupling

Disposition: `ENGINEERING_CLOSED_PENDING_INDEPENDENT_REREVIEW`

The unchanged `ScorePriorRequest` contract moved to the market-free
`football_events.score_prior_request` leaf. The legacy service import re-exports the exact same
class. A fresh process blocks all `dmf_pulse.markets` imports while importing and constructing the
OpenFootball result/bundle and leaf request. Frozen packaged GCS schemas remain exactly equal to
runtime schemas, and 212 inherited GCS tests pass.

## CSP-IR-004 — unexpected transport exception disclosure

Disposition: `ENGINEERING_CLOSED_PENDING_INDEPENDENT_REREVIEW`

Unexpected ordinary exceptions at the injectable transport boundary become bounded
`SOURCE_UNAVAILABLE` errors without upstream strings, representations or arguments. Failure on
calls 1, 2, 3 and 4 retains exact accounting. Service and CLI serialization contain no malicious
sentinel. `KeyboardInterrupt` and `SystemExit` propagate.

## Preserved facts

- OpenFootball commit: `f27dcbef681db2c3195f9def62316ce497278781`
- Rights profile: `openfootball_football_json_score_prior_v1` version `1.0.0`
- Method: `PL_LEAGUE_HOME_AWAY_MEAN_3_COMPLETE_SEASONS_V1`
- Sample/totals: `1140 / 1839 / 1567`
- Rates: `1.613158 / 1.374561`
- Source mode: `RECONSTRUCTED`
- Market evidence/current-team-strength/production claims: `false / false / false`

No PR, merge, production activation or human acceptance was performed.
