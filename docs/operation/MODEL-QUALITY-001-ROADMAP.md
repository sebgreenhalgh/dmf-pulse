# Prioritized implementation roadmap

Priorities reflect dependency order and ability to validate independently.
Impact estimates below are qualitative, not measured accuracy gains. Effort is
relative engineering complexity; no unsupported delivery dates are implied.

| Order / bounded ticket | Change and dependencies | Effort / runtime / risk | Evidence and acceptance |
| --- | --- | --- | --- |
| 1 / MQ-001-DIAGNOSTICS | Implement `dmf analysis quality` and normalized derived fixture/GW/component views from existing typed snapshots. No model dependency changes. | Low/medium; offline; measured scaling; no provider or model execution. Research branch implementation in this programme. | Deterministic/null/hostile identity and PMF tests; exact marginal accounting with unavailable joint terms; v1 read compatibility; transactional/idempotent v2 copy migration; history hashes unchanged; installed wheel; independent review. No skill improvement claimed. |
| 2 / MQ-002-MATCH-MEMBERSHIP | Prepare a challenger to `_current_history`'s use of current club for past GW aggregates. Keep champion immutable. Exact retained per-fixture membership is prerequisite; exclude ambiguity rather than assign a familiar team. | Medium; linear preprocessing; low compute, potentially high data-coverage cost. | Owned transferred-player, changed-club, ambiguous/blank/DGW fixtures; no history row rehomed without proof; zero provider acquisition; report excluded counts and common-sample minutes/points differences. Fresh approval before production numerical activation. |
| 3 / MQ-003-REAL-CUSTODY | Connect existing `player_lab.real_store` freeze/label/evaluate pipeline to completed operational outputs and existing B0-B4 benchmarks. Depends on qualified protocol, research sources, finality and retention approval. | Medium; small derived metadata cost; rights/late-freeze risk. Highest direct value to knowing model quality. | Actual predeadline issue/freeze timestamps, model/source/rules hashes, full expected population, finalized labels, missingness/late rejection, chronological holdout and paired GW-block intervals. SQLite receives only authorized derived scorecards. No backfilled prospective claim for GW10. |
| 4 / MQ-004-CAPTAIN-MC | Retain existing fixed-XI ordered captain/vice evaluator counterfactual aggregates and actual MC policy/paired decision precision. Depends on derived retention contract, not new player model. | Medium; ordered pairs bounded by XI size; aggregation/storage inexpensive relative to tactical search. | Captain/vice/no-appearance/normal and TC multiplier tests; paired deltas on same scenarios; independent seed stability audit; exact policy thresholds exposed. Do not reconstruct unavailable GW10 comparisons. |
| 5 / MQ-005-MINUTES-CALIBRATION | Evaluate current role/minute shrinkage and reconciliation against naive last-start/recent-minutes/position benchmarks; retain individual evidence counts, prior weights and reconciliation distortions. Depends on MQ-002/003. | High statistical effort; moderate CPU; sparse histories/rotation risk. | Preregistered chronological cohorts; starts Brier/log/reliability; unconditional and conditional minute scores; stable probability normalization; champion/challenger freeze; no confidence upgrade without evidence. |
| 6 / MQ-006-CURRENT-PLAYER-SHADOW | Reuse R9B posterior and R9C four-world adapters; current assists/cards/saves supported when qualified; preserve explicit goal-update block without nonpenalty decomposition. Depends on MQ-003 and current source evidence. | Medium/high; four paired forecast worlds; source purpose and overfitting risk. | Common frozen input/seed/market/minutes/rules; low/high shrinkage sensitivity; complete cohort uncertainty/benchmark scores; zero exposure is not zero rate; isolated promotion approval. |
| 7 / MQ-007-THREE-GW | Connect existing Stage-11 rolling mode and new SQL per-GW summaries; qualify actual distinct fixtures/markets and expose present independent-GW/no-information-revelation limitation. Depends on source scope and MQ-003/005. | Medium/high; bounded candidate search; runtime must be measured on full owned catalogue. | Three genuine distinct GWs, no duplicated forecast padding; current FT/ownership/price state, terminal assumptions, legal exact declared search scope; distribution/objective parity; missing horizon fails visibly. Joint transition challenger needs separate validation. |
| 8 / MQ-008-CHIP-ROUTES | Connect existing Stage-14 WC/FH/BB/TC route evaluators and finite-token scheduler to legal Stage-11 candidate policies. Depends on MQ-007 and genuine inventory/continuation inputs. | High; route/candidate scaling and opportunity-cost risk. | Legal 15-player budget/club/position squad; WC-now/normal/delayed; FH restoration; BB autosub overlap/preparation; TC effective extra copy; common hold continuation, scenario/rules hashes, best-supplied-route disclosure. |
| 9 / MQ-009-TEAM-AND-LONG-HORIZON | Reuse existing team-strength/parameter-mixture challenger. Only then research supported 5/8-GW transition/horizon forecasts, future price and rank/EO cohorts. | High; fundamental data/protocol dependence; not an eight-copy sum. | Held-out score/point calibration and benchmark gain; cohort rights; shared latent paths, injury/fatigue/rotation transitions and time-varying uncertainty; isolated independent promotion review. |

Before items 2-9, execute bounded **MQ-000-MATHEMATICAL-CONTRACTS** review:
resolve the generic RPS target-grid contract and Stage-11 mean-between-quantiles
rejection using the retained exact counterexamples. Effort is low/medium, CPU
negligible, and no new football data is needed for algebraic regressions.
Acceptance requires representation-invariant scores on a declared common target
grid (sparse/gapped/negative support and out-of-support outcomes), and acceptance
of valid rare-tail distributions whose mean exceeds p90 when fields are actual
quantiles. Preserve finite values, ordered quantiles, legality, versioned metrics
and old artifacts. Existing accepted modules stay frozen in this programme;
changing their numerical/public contracts requires separate independent review
and applicable acceptance. This is not a historical GW10 defect claim.

## Sources and rights assessment before any acquisition

| Candidate evidence | Current basis / cost knowledge | Statistical value and gate |
| --- | --- | --- |
| Already authorized current FPL catalogue, fixtures and event aggregates | Existing exact operational routes and owner-attested purpose; this audit uses no calls or credits. No new research retention or historical match-time membership right is inferred. | Recent participation and outcomes are useful only with correct fixture/membership/finality and custody. Prepare exact fields/routes/purpose/budget for separate research qualification. |
| Existing pinned OpenFootball complete results | Existing CC0/pinned three-season qualification; no new request or price estimate. | Strong simple score-prior baseline; existing team-strength challenger can use qualified historical results under its exact protocol. No player roles/minutes/BPS supplied. |
| Packaged Wyscout-derived historical role artifacts | Existing repository-governed derived resource and cutoff only; underlying dataset/reuse rights must be verified for any new acquisition or training, not inferred from artifact presence. No current commercial quote established. | Useful shrinkage baseline; old event population/fine-role mismatch and current-player coverage limit transferability. Do not sell old individual lineage as current calibration. |
| Existing Odds current/horizon route | Exact transient recommendation scope, account/territory and credit ceilings remain binding; no query, quote refresh, new quota or charge is authorized here. | Market anchoring and horizon coverage; not a replacement for player evidence. Historical odds/training need distinct rights, price/coverage assessment and exact predeadline timestamps. |
| New detailed player event/history supplier | No authenticated supplier scope, licence, price or purchase authorization established in this audit. | Potential nonpenalty xG/xA, substitution, roles, BPS/defensive event improvements. Require exact source/licence/retention/training terms, coverage/latency/identity checks, written cost ceiling and independent incremental benchmark protocol before using it. |

This is a concrete qualification queue, not permission to use an additional
supplier. No new data was acquired to fill an audit cell.

## Database rollout gate

v2 adds views and retains old JSON and SQL definitions, but the currently signed
v1 reader rejects `PRAGMA user_version=2`. Production migration must wait for a
reviewed rollout/rollback plan (compatible rollback reader or approved schema-only
reverse migration on a closed, verified backup). No live migration or installed
release replacement is part of this programme. Merely passing v2 research-copy
tests does not clear that deployment gate.
