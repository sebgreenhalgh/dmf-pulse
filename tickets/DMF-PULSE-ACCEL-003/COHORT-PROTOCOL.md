# Player cohort protocol v1

This companion execution protocol preserves all existing player-forecast-v1,
player-final-outcome-v1, registered source bytes and PostgreSQL 0007 gates. It
implements complete cohort custody and reporting; it does not qualify real
acquisition, retention, a model promotion or production activation.

## Population and original custody

`CohortProtocol` preregisters a season-scoped player/fixture population, both
model identities, dependency scope, experiment identity and missingness policy.
Every registered player must occur in every registered Gameweek. A closed
`ForecastCohort` contains the exact canonical model-by-target product. Each
forecast retains its own rules, model, code, source, input and cutoff hashes;
original `MemoryLedger` receipts authenticate it. Registration precedes forecast
generation, generation precedes the custody timestamp, and custody precedes the
official deadline. Missing, duplicate or substituted targets block closure.

The executable owned fixture includes **all four registered synthetic players
across two synthetic Gameweeks**, eight player/GW targets and sixteen forecasts
for two models. It is not the current EPL population. The synthetic input asset
declares those four players and the two Gameweeks; neither holdings nor observed
points select inclusion. All forecasts close before any outcome body is opened.
Its historical simulation clocks are explicitly synthetic. They cannot prove a
real issue time. A real cohort will require separately accepted append-only
custody with a trusted issue clock and qualified source/mapping evidence.

Forecast target identity contains season, GW, canonical player UUID and the exact
canonical fixture tuple. Injuries, zero minutes, blank Gameweeks and later club
transfers must not cause outcome-dependent exclusions. A real preregistration
must record every catalogue inclusion/exclusion and its pre-origin reason,
retain all eligible players, and block if the complete identity/fixture mapping
or forecast population is unavailable. No manager-specific private facts are
required to score an all-player population.

Final labels must match all eight original targets exactly. Time after a match
alone does not prove finality. The source context requires all fixtures finished,
an explicit checked event, and the 2026/27 next-day 09:00 London lock. A report
requires every label usable by its assessment time. A missing result blocks the
entire report; it is never dropped or zero-filled. An extraordinary correction
creates another immutable complete GW vintage. Do not mix original/corrected
players within one GW. Original report hashes remain independently reproducible.

## Metrics, holdout and claims

`PlayerEvaluationService` authenticates custody and joins, then calls existing
`evaluate_players`, `compare_holdout` and Stage-12 scalar point metric kernels.
It does not implement a second statistical evaluator. The report includes mean
MAE/RMSE/bias, complete PMF scoring,5+ Brier/log loss, reliability/calibration,
central 80% coverage,13 component point-error panels and actual minutes error.
Per-target distribution diagnostics retain log-score boundary status, interval
width/score and other original Stage-12 outputs. Calibration reports retain
INSUFFICIENT_VARIATION or numerical failure when applicable; existence of a
metric does not establish that the sample supports a calibration conclusion.

The inherited preregistration uses GW 2 for development and later GW 3 as untouched
paired holdout, four players in each. Both models share cutoff, rules, targets
and dependencies. The report shows this engineering comparison and forbids
promotion. It reports no uncertainty estimate or skill claim for this tiny
synthetic fixture. Repeated players and shared fixtures are not independent
samples. A later real programme needs preregistered contiguous development and
holdout origins and an accepted uncertainty/reporting/promotion policy; no sample
size or stopping threshold is invented here.

The accepted B0-B5 ladder remains visible with typed unavailable reasons:
recent points, official form, market only, market+minutes, complete Pulse and
labelled hindsight each need a qualified matched information set. The analytic
synthetic PMF is not the complete Pulse B4 benchmark. The existing zero-points
oracle remains a diagnostic, and cannot satisfy B0 or prove benchmark success.
No sequential manager-policy replay is claimed from forecast accuracy.

## Diagnostic sidecars

Existing v1 seals are unchanged. `MinutesSidecar` binds each original label hash
and registered source to authenticated original raw per-fixture minutes. The
source bytes, context, exact official/canonical mapping and label values are
revalidated before reading those counts. Appearance points never infer minutes.
Actual start labels are absent in the owned source, so observed starts remain
unavailable. Forecast start/60+ fixture probabilities were not frozen in v1;
those scores remain explicitly unavailable. A substitute may play 60+ minutes.
In a DGW, aggregate minutes>=60 does not define fixture 60+ status or a GW event
probability. Future sidecars need separately qualified fixture probabilities
and independently observed start labels before either diagnostic can be scored.

## First genuine future candidate: inactive

Public official indexed HTML researched29 October 2026 identifies2026/27 GW 9,
deadline **2026-10-31T11:00:00Z**. Source:
[Premier League article 4750452](https://www.premierleague.com/es/news/4750452/everything-you-need-for-gameweek-9-of-fpl-with-the-latest-tips-and-advice),
published29 October 2026. Direct article opening returned an access error. This is
indexed official textual evidence, not an observed FPL API deadline/schema.
`future_cohort_proposal` expires the candidate at its deadline and reports
EXPIRED_NEXT_DEADLINE_UNRESOLVED thereafter. It never authorizes execution.

Before any real freeze, separately qualify the whole catalogue/fixture population,
every source dependency, all storage/display/evaluation purposes, exact source
routes/account/budget/code, future official deadline, rules/model/input hashes,
forecast origin/cutoff, baselines, finality/correction policy and untouched
chronological holdout. If this misses GW 9, select a newly verified future origin.
Never backdate a freeze or call a completed Gameweek prospective. Real cohort
size remains0: **NO RIGHTS-QUALIFIED REAL PROSPECTIVE COHORT**.

## Dependency qualification matrix

| Dependency / owner / version | Acquisition / current purpose | Retention and derived evaluation | Training / display / required decision |
|---|---|---|---|
| FPL catalogue, players, fixtures, prices; PL/Opta; private operator profile v1 | Existing exact operator read-only routes only; no expanded outcome route | Raw, derived, cache and backup DENY; resulting forecasts cannot be retained | Training DENY; private transient only. Internal risk acceptance is not provider permission; supplier permission and source qualification remain necessary |
| Private manager state; manager/PL; same profile | Exact authorized manager and routes | Retention DENY; exclude this unnecessary dependency from all-player research | No public display; no manager facts/hash laundering in retained cohort |
| Final GW player labels; PL/Opta; candidateGW-wide route | New route unapproved; no live observation performed | No real source-registry or label-storage qualification | New access/retention/evaluation purposes and exact schema qualification required |
| H2H/totals; TheOddsAPI; existing L8 profile | Consumed one-shot is unavailable for another run | Existing purpose notes require zero retention; raw/training/backup unresolved | Recurring transient and retained research are separate new purposes, with source terms/plan and owner decisions |
| Historical score priors; OpenFootballCC0 pinned commits; score-prior/team-strength profiles v1 | Existing exact EPL/commit/private purpose | Raw/derived/cache/backup permitted within those profiles; keep commit/path/licence/usable provenance | Training permitted within source profile purpose; private display only. Does not qualify other forecast dependencies |
| Starts/minutes/allocation; current Grade-E historical/FPL ancestry and owned parameters | Inherit every upstream source scope | A derived forecast inherits forbidden FPL retention; owned model code cannot erase that lineage | No current model substitution or unsupported confidence claim |
| New starts/events/xG/xA; unselected supplier/version | No entitlement established | Written season/field, derived, retention and evaluation rights required | Training/public/private display separately qualified; owner expenditure does not grant a licence |
| Rules, owned model/config/code; exact accepted hashes | Owned compiled artefacts with official factual provenance | Owned immutable retention available, excluding embedded restricted source data | No model promotion/activation; preserve accepted rules and parameters |
| Generated scenarios/transformed features/final forecasts | Whole information-set lineage | Intersection of ALL dependencies; label permission alone cannot permit storage | No blanket derived-data exemption or synthetic wrapper |
| Existing exact owned synthetic fixture registry/profile | Offline/manual synthetic acceptance only; automated access DENY | Raw/derived/backup permitted for exact registered owned resources | Training/public display/redistribution DENY; scientific real sample0 |

Python and SQL source registries remain closed. No forbidden write is attempted;
CLI input assertions do not add registry entries or qualify arbitrary sources.
