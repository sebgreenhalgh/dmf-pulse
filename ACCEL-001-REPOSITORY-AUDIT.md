# ACCEL-001 repository audit

Fetched origin on 2026-10-28 before implementation. Main remains
99418f3316277f4dae347d80358d5dd5a09655b2 (2026-08-31). D2 is
e8efdd2c1051f75accdb2bd1f635ca02ed410241. INITIAL-SNAPSHOT.json records all 117
remote refs with separate ancestor-of-main and ancestor-of-D2 flags, 85 protected
files and 104 historical artifacts. Existing dirty availability work is untouched.
No histories merged/rebased/cherry-picked. D2 descends from private one-command,
allocation, team-strength, A02/D1/A03 work; protocol branch ancestry is recorded
separately, not inferred from its date. A03 consumed ref f11b3a2 contains receipt
bd64193a985b1629d0b1cec68ddc6d539e1719d814d0ab52a1e5f6dd2e03d3c9.

GitHub has no open PRs. Open issue #14 is a historical Stage15 transport ledger,
whose final seal records success at 17b6aa576459c652e14015dcfd7b7cf0bffd6f9d;
earlier failed runs remain visible. It is not a current unresolved product bug.

## Status vocabulary and authority

Implemented, integrated, tested, independently reviewed, human accepted and active
are separate assertions. Branch existence proves none of the latter five.
Stage acceptance JSONs for 9/11/12 retain human-pending records despite later
integration. Stage13 is explicitly shadow/uncalibrated. No wholesale human acceptance
of Stages1–15 is inferred. Rules are VERIFIED/production-eligible in source but the
private exception is transient, not ACTIVE production activation. Full Stage16
completion is unestablished; DMFP18 header is PROPOSED while specific UI ADRs are
ACCEPTED. Authority and provider profiles are hash-bound in INITIAL-SNAPSHOT.

Read-only independent governance, P01 and private-engine reviews inspected source,
tests/contracts and evidence. Authority anchors: DMFP20 ADR-DATA-004/005/006,
OPT-002/004/005, CHIP-002, RANK-002, ASSUR-006, UI-001/002/003 and IMPL-001/003.
No fresh online provider terms/rules research is performed because this programme
prohibits football-provider access and changes no provider permission or FPL rule.

## Subsystem inventory

| Subsystem | Actual code and executable/test evidence | Integration/status and limitation | Next justified step |
|---|---|---|---|
| 1 Rules/current state | rules compiler/capabilities; ingestion/fpl/current.py, current_state.py; rules/current-state CLI and integration tests | Mainline kernels; VERIFIED full-season rules; private state transient; cutoff gates do not protect publication time | Deadline-safe one-command publication (C) |
| 2 Odds | ingestion/odds, markets/current.py; odds/market CLI; current-market rights/identity tests | Private pipeline consumes normalized lawful transient constraints; profiles are purpose-bound, not new authority | Preserve rights-before-side-effects; no acquisition now |
| 3 Identity | automatic_mapping.py, current_state.py, private_v1/automatic_inputs.py; oriented/season/context fixtures | Canonical IDs and bijective mappings integrated; unresolved evidence fails closed | Preserve strict identity under candidate metadata (AB) |
| 4 Score priors | ingestion/openfootball, football_events/team_strength*; shadow CLI, replay/covariance/prospective tests | Mainline historical score prior; later plug-in/mixture branches shadow only; P01 unscored | Synthetic readiness, then separately authorized prospective labels |
| 5 Availability/minutes | availability/current_model.py; automatic_inputs.py; roster/substitution/GK and current-model tests | Current-season empirical-Bayes minutes, shared256 samples, disclosed global-prior fallback | Lawful calibrated current allocation/minutes evidence; no experimental promotion |
| 6 Events/allocation | football_events/service.py; private service._project_fixtures; GCS fixtures/oracles | Stage7/8 market/minutes/prior integration; historical Grade-E/stale carry-forward weak | Calibrate allocation with lawful longitudinal labels |
| 7 Full points | fpl_points/service.py/gameweek.py; Stage9 scoring/rules/MC tests and CLI | Full distributions integrated; accepted rules bound, same scenario IDs for comparisons | Expose existing MC/evidence limitations at pulse surface |
| 8 Uncertainty | shared Stage7/8/9 scenarios; rolling._horizon_comparison; horizon oracle | Cross-GW independent product, no future-information topology; parameter mixture shadow only | Preserve disclosures; empirical validation before richer model |
| 9 Prices/timing | prices/service.py and prices CLI; integration/prices | Implemented standalone; shadow, target-season uncalibrated, rights blocked; private prices constant | Calibration and lawful current data before integration |
| 10 Transfers | optimisation Stage10/11; private_v1/rolling.py; rolling_service/horizon_candidate_oracle tests | 1GW plus explicit3GW integrated on readiness descendant; bounded incoming24/root2; zero terminal | Operational deadline guard; retain exactness only within declared space |
| 11 Captain/chips | chips/captaincy.py used by private service; chips service/CLI integration tests | Captain/vice integrated; private rolling NO_CHIP_EXPLICIT; broader chips standalone | Opportunity-cost evidence before chip use-now recommendations |
| 12 Rank | rank_strategy services/CLI; exact mini-league/synthetic field tests | Standalone; private POINTS_MODE_ONLY; no representative lawful cohort | Cohort evidence gates before active integration |
| 13 Evaluation | evaluation services, public prospective/P01 modules; evaluate and team-strength CLI/tests | Historical and prospective machinery; actual P01 immutable/unscored; A02/A03 consumed | Inactive D3, exact-type fix and synthetic pipeline (AB) |
| 14 Private operation | private_v1/one_command.py and cli/pulse.py; real transport-injected1/3GW tests | Runnable transient pipeline on branch; can currently finish past deadline and still say ready | Correct service/render/CLI deadline boundaries (C) |
| 15 Ops/security | assurance, system/process, rights, data_model/database/migrations; doctor, manifest, secrets, installed-wheel and PG tests | Twenty-job CI with16 coverage shards; evidence and data retention governed | Exact-SHA release and protected artifact verification |
| 16 Decision experience | service._report, one_command._display_report, rolling.render_rolling_report | Useful CLI already exists; full API/presentation absent; pulse omits available quality fields | Existing structured quality disclosure if mandatory slices secured (D) |

Fresh independent baseline: pulse CLI11 tests pass (5.28s); rolling service plus
tiny horizon oracle8 pass (170.44s). D2 CI40749235436 is prior baseline evidence,
not ACCEL release evidence. Current programme tests and CI are recorded separately.

## Ranked implementation choice

See gap-register.json for severity, dependencies, evidence, rights, scope and tests.
P1 deadline publication defect is selected over speculative model changes because
it can invalidate a real recommendation despite correct numerical optimisation.
P01 AB is mandatory and independently valuable: descriptive schema variation must
not weaken identity, and synthetic readiness must not look like an actual P01 score.
The linked-result bool/float defect is independently reproduced and will be fixed.
Optional quality reporting uses existing values, not invented probabilities.

Separate clean sequential worktrees preserve reviewable domains without merging
independent authority histories. Mainline integration, human acceptance and production
activation are future owner decisions, not outcomes of this programme.
