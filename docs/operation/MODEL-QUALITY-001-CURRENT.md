# Current model quality: DMF-MODEL-QUALITY-001

Audit base: fetched `launch/GW10-real-pilot` at
`df26ab0723dea99469fe4c98423402ea91f85776`, 2026-11-07. This report describes
implemented code, not a claim of predictive skill. Private numerical findings
and authenticated original-output comparisons stay in ignored
`review_pack/private-audit/`; the GitHub repository is public.

## Authority and boundaries

`specs/manifests/authority_manifest.json` resolves A3/A6/A7/A8/A9/A10/A12 and
B1-B6. DMFP-20's accepted DATA-004/005/006/007, MIN-001/002/003,
EVT-001/003/004/005, PTS-001/002/003/004 and EVAL-001..006 control temporal
eligibility, missingness, scenario scoring and validation. MIN-004's full
competing-risk hazards and EVT-002's projection family are provisional choices,
not evidence that the mature architecture is deployed. The first implementation
changes diagnostics and derived SQL access only. All numerical source bytes,
provider routes, model resources and rules remain unchanged.

## Trace of the ordinary current path

| Stage | Implemented path and mathematics | Evidence, uncertainty and shortcuts | Tests and retention |
| --- | --- | --- | --- |
| Acquisition/identity | `private_v1/one_command.py:PrivateV1OneCommandService`; `automatic_inputs.py:build_automatic_player_identity_map`; direct FPL catalogue, fixtures and finished event observations; explicit official IDs map deterministically to UUID5 canonical identities. `presentation.py:build_presentation` binds official fixture ID, GW and both teams. | Current supplier-observed data are transient. Current catalogue team identity is used for retrieved past event aggregates. No event-time membership reconstruction occurs in `_current_history`. Provider authentication and owner-attested permission are separate facts. | `tests/unit/private_v1/`, `tests/unit/ingestion/`. SQLite saves typed derived catalogue and source hashes/times, not source bodies or executable inputs. |
| Team score prior | `ingestion/openfootball/service.py:CurrentScorePriorService`: independent Poisson league home/away means from three pinned complete seasons (1,140 matches). | Explicit `WEAK_LEAGUE_LEVEL_SUPPORT_PRIOR`; does not individualize a club's attack/defence. Existing `football_events/team_strength_model.py:fit_team_strength` and mixture/parameter-draw machinery are separate challengers, not the ordinary prior. | OpenFootball and team-strength unit/contract tests; private derived fixture summaries may retain projected score diagnostics, but historical imports may lack them. |
| Market/Stage 8 | `markets/current.py:CurrentMarketConstraintService`; `football_events/service.py:ScoreDistributionService`; `score_projection.py`: proper score simplex, independent Poisson prior and uncertainty-weighted soft KL projection. Packaged policy sets goal-grid/tail limits, family caps and fallback permission. | Markets constrain a coherent team distribution; no claim that markets identify all player events. Correlated markets/family weights, stale or partial coverage and prior-only fallback need prospective residual/proper-score checks. No residual or calibration inference from a final xPts table. | `tests/unit/football_events/`, `tests/property/football_events/`, market temporal/coherence tests. Ordinary derived presentation is retainable; original GW10 fixture objects were not retained. |
| Stage 7 starts/minutes | `automatic_inputs.py:_current_history`, `_build_automatic_model_minutes_for_targets`; `availability/pipeline.py:fit_projection_artifact`, `predict_minutes_baseline`; `role_model.py`, `minutes.py`, `lineup.py`, `current_model.py`. START/BENCH/OUT utilities combine position priors and recency-weighted observed role counts; coherent lineups have exactly 11 starters. Unconditional 91-bin minute PMF mixes role-specific distributions and zero mass. | Global fit uses the frozen synthetic MIN-007 training set. Current event minutes/starts update player histories; that is real input use, not real calibration of the frozen priors. Role strength 2, minute strength 3, recency decay .85, history window 12 are policy values. Team scenarios are reconciled to 990 player-minutes and substitution bounds; reconciliation can distort individual marginals. Hard exclusion is removed/status `u`; other availability signals are not a fully calibrated injury model. | MIN-007/current-model/coherent-lineup tests. New fixture metric view exposes retained PMF and reasons. Historical absence remains absence. Stored Stage-7 aggregate confidence differs from Stage-9 evidence grade. |
| Player allocation | `fpl_points/player_prior.py:build_automatic_current_gw_stale_prior_policy`, `bind_current_gw_fixture_allocation_profiles`; packaged `gw1_private_player_allocation_prior_v1.json`. Retained GW1 profile is rebound exactly if official/canonical player and team match; otherwise an explicit same-position donor is required. | Prior cutoff is 2026-08-21, with role-prior version `GW1_WYSCOUNT_EPL_2017_18_ROLE_PRIOR_CANDIDATE_V1`. Public artifact has 599 profiles: 482 goal/assist INDIVIDUAL lineages, 117 FPL_POSITION; all auxiliary lineages are FPL_POSITION. An INDIVIDUAL label is historical channel evidence, not recent player calibration or wholly individualized points. No per-player shrinkage weights/counterfactual xPts are retained. | `tests/unit/fpl_points/test_player_prior.py`, current player shadow tests. R9B Gamma-Poisson `current_player_posterior.py` and four-world R9C shadow adapters already exist. They are not the champion; current goals lack nonpenalty decomposition. |
| Events/Stage 9 | `fpl_points/allocation.py`: sample team score, participation and timed events; allocate only to on-pitch players; conserve team goals; explicit penalty hierarchy/proxy, own goals and assist mechanisms. `rules_adapter.py` applies the exact bound rules; bonus uses joint BPS ranking and ties. | Packaged allocation YAML explicitly labels illustrative TEST/REPLAY defaults. BPS and defensive auxiliary rates are pooled/partially zero; zero auxiliary rates can be structural approximations rather than measured player zeroes. Static historical role priors, penalty assumptions and auxiliary residuals need isolated challenger validation. | Allocation, goal conservation, on-pitch eligibility, exact rules/BPS ties, component reconciliation, deterministic named RNG tests under `tests/unit/fpl_points/`, property/golden/integration/assurance suites. Warehouse retains derived PMFs/components when present; source scenario matrices remain excluded. |
| Monte Carlo | `fpl_points/monte_carlo.py`, `summaries.py:weighted_quantile`; ESS = 1/sum(normalized weight squared), mean SE = sqrt(weighted variance / ESS), threshold SE and interleaved-batch quantile span. | Ordinary `one_command.py` constructs policy ESS>=1, maximum mean SE 100, maximum probability SE 1, maximum quantile span 100, two batches. Packaged simulation policy instead requests ESS>=1,000, mean SE<=.10, probability SE<=.01, span<=3, four batches. A normal-path PASS therefore certifies neither the packaged precision target nor predictive calibration. Finite-sample ESS does not establish cross-world independence. | Numerical tests exist; new diagnostic reports retained mean SE and labels unavailable policy values. Independent seeds/paired plan precision and winner-selection error still need prospective measurement. |
| XI/captain/transfer | `optimisation/tactics.py`, `autosub_evaluator.py`; Stage-11 `multi_gameweek_solver.py`, `private_v1/service.py:_stage11_request`, `_verify_captain`. Exact legal tactical enumeration for the declared squad/action/scenario universe; captain/vice verified by existing `chips/captaincy.py:optimise_captain_vice`. | Ordinary one-GW objective assigns zero terminal value. Incoming candidates are screened; exact within that declared set is not a global optimum over every player or horizon. Captaincy maximizes joint expected manager points, not standalone captain xPts or ownership. Transfer frontier is non-nested where disclosed; its differences are not individual move attribution. | Existing tactical/transfer/legal/captain tests. New normal snapshots already require authenticated optimizer evidence; older GW10 snapshot lacks it. Captain-only counterfactuals remain absent. |

## Specific GW10 questions and evidence limits

**Grade E:** it is explicitly assigned in `player_prior.py` for both governed
donor and stale current-GW binding, then propagated to point summaries. It is
not computed by noticing that every player lacks history. Minutes can have
different grades. Private audit quantifies exact carried INDIVIDUAL versus
position-only rows; neither row counts nor the xPts sums of those rows measure
the causal contribution of individualized evidence. That requires freezing an
ablation on the same source/seed/lineup/market surface.

**Identity:** catalogue labels come from current official IDs, not name-based
historical football knowledge. Unusual combinations are not proven errors.
Original raw membership bodies were not retained under the applicable rights.
The demonstrated code risk is historical `_current_history` assignment: the
current player's club chooses a past fixture from a GW aggregate, even after a
transfer. A past-gameweek aggregate alone cannot establish match-time club.
Do not silently rewrite GW10. Prepare an independently tested identity-aware
challenger, excluding ambiguous rows unless an exact retained fixture membership
can support them. Tests also need blank/DGW and transferred-player cases.

**Zeroes:** retained zero xPts co-occur with zero expected minutes and start
probability; the historical evidence does not distinguish hard exclusion, sparse
history, scenario-sampled nonappearance, and other causes player by player.
There is no missing-projection null silently filled with zero in the saved view.
Positive but small probability can produce no sampled appearance. A future run
must retain minute PMF, confidence reasons, availability evidence class and
reconciliation diagnostics to classify causes. New diagnostics preserve this limit.

**p10:** `weighted_quantile` returns the least integer x with F(x)>=.10.
Zero p10 is compatible with ordinary nonappearance and low scores. It is not
proof of zero minutes or of bad quantile code. With 256 equal-weight scenarios,
each mass is 1/256; the 10th percentile is the 26th order statistic. A reference
independent Bernoulli probability SE is at most .03125 at this size; this is a
numerical reference, not an inferred calibration interval. No original PMFs
survive for GW10 to determine individual tail masses or convergence exactly.

**Team reconciliation:** scenario scorer computes
`base_points + captain_bonus_points`, where base already counts autosub entrants.
The historical arithmetic identity is
`team mean = XI marginal sum + standalone captain mean + residual`.
The private report records each exact term. The residual is deliberately
unattributed: its split into autosubs, effective vice captain and any difference
between scoring/presentation surfaces cannot be recovered from marginals. No
historical mathematical defect or full correctness proof follows from that residual.

**Palmer/Haaland:** for a fixed XI and normal captain multiplier, expected extra
captain points are `E[P_c] + E[1(c absent) * 1(v appears) * P_v]`.
The reverse pair has a different contingency term. Start probability alone is
insufficient because a substitute appearance also prevents vice activation.
The engine optimizes the complete manager score and legal vice interaction.
The retained result does not contain the alternate fixed-XI score or its paired
delta, so it cannot identify the exact historical reason or numerical advantage.
Do not claim risk/ownership caused it: this objective is expected points.

Prospective captain evidence should save fixed squad/XI/bench, each ordered
captain/vice pair, scoring/rules/projection hashes, no-appearance probabilities,
expected effective-captain bonus, paired delta PMF/SE and resolution frequencies.
Store only approved derived aggregates, not raw per-player scenarios. Use the
existing evaluator; do not build a second captain engine.

## What can improve accuracy next

Prioritize exact match-time identities, player evidence custody, real minutes
calibration, and prospective benchmarks before extra solver complexity. Reuse
the existing player posterior and team-strength shadows after their source and
promotion gates. No measured skill gain has been demonstrated in this audit.
See the validation scorecard, capability matrix and bounded roadmap for the
evidence necessary to make that claim.
