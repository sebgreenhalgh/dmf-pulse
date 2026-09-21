# Original research definitions recovered before implementation

The original local research source is `dmf_team_strength_study_20260921.py`; its pinned source
repository is `openfootball/football.json` at `40b3e1b7391932d133287115106304444bf297e1`.
Original research script SHA256:
`b2d2d9870a605bea1909fd94ac041e9cf3a11556fdac9a148a3ec9263278c398`.
The offline audit compares all source hashes to the authenticated P0 registry.

The recovered `design` function calculates `mean_goal = float(y.mean())` over both score
observations of every included match, BEFORE the likelihood decay weights are constructed.
Thus the accepted penalty uses the **unweighted** arithmetic mean:

`mean_goal = sum(home_goals + away_goals) / (2 * match_count)`.

Both penalty coefficients equal `12 * mean_goal`. The minimized objective is
`sum(w * (exp(eta) - y * eta)) + 0.5*kappa_a*||attack-centre_a||^2
+ 0.5*kappa_d*||defence-centre_d||^2`. Mu and the one global home effect are unpenalized.
The likelihood factorial term is constant in the parameters and omitted during optimization.

The recovered `build_seasonal_effects` fits each completed EPL season independently, with no
decay, neutral centres, and four-match attack and defence priors on the same unweighted goal
scale. `cohort_centres` averages the reconstructed attack and defence effects of entrant club
seasons strictly earlier than the forecast season. A production implementation must additionally
ensure these historical season inputs are available under its dataset cutoff policy. The first
corpus season has no preceding membership and contributes no entrant cohort. Current entrants
receive the cohort centre; other clubs receive zero. This four-match auxiliary calculation is a
fixed part of the accepted cohort algorithm, not an operator-selectable main-model policy.

The original replay groups the 2025/26 holdout into source Matchdays 1--38, takes each block's
earliest played date as the forecast origin, and fits once per block. Its historical predicate
is `played_on < cutoff`. Live eligibility is governed separately by P0's D+2 and receipt/usable
requirements. The audit found exactly one training-population difference: the Matchday 34
origin on 2026-04-21 excludes the 2026-04-20 result under D+2. Accordingly the original research
mathematical reproduction is a separately labelled metrics-only diagnostic; it cannot emit a
governed model artifact or fixture bundle. The governed replay enforces D+2. Both are explicitly
RECONSTRUCTED. The research contract review accepted this separation; no tolerance adjustment
may disguise the population difference.

Predeclared reproduction tolerance, before running the new historical replay: absolute
`0.000002` for baseline/candidate exact-score log loss and their difference against the
six-place research targets. This includes research rounding and the original L-BFGS stopping
error versus the tighter approved Newton solution. It is not a retuning allowance. The
governed D+2 report must state its separate value and population; this tolerance does not
authorize treating that population as the original research reproduction.

Research metrics normalize identical 0..36 joint score support for both models. Totals Brier is
the mean of over-1.5, over-2.5, and over-3.5 Briers. Goal RPS is the mean of the two marginal
sum-of-squared-CDF-errors over thresholds 0..35. Goal MAEs use the unrounded Poisson means.
The time-valid baseline uses 2022/23, 2023/24, and 2024/25 for the 2025/26 holdout.

The exploratory research uses NumPy/SciPy and clipped optimization trial predictors. These
dependencies and clipping are not authorized for the implementation. The accepted 001A method
is analytic float64 damped Newton with finite-rate rejection and no coefficient/rate clamping.

## Retention and publication

The repository is public. P0 permits private raw/derived retention but denies redistribution.
Raw season files, canonical fixture registrations, fitted arrays and per-fixture outputs remain
in ignored local storage. Tests use synthetic inputs. Mandatory real-corpus acceptance takes
an explicit private input directory, performs no network access, and fails if unavailable or
inauthentic. It is not skipped, replaced by synthetic evidence, or claimed as public CI coverage.
Published evidence is limited to code, source identities and safe aggregate summaries.

## Model and execution identity

`TeamStrengthModelStateV1.semantic_sha256` authenticates the deterministic dataset-bound
fit, coefficients, numerical diagnostics, information/covariance lower triangles and policy.
The separately hashed `TeamStrengthModelArtifactV1` execution envelope binds this state to
actual `fitted_at` and `usable_at`. Repeating identical semantic input reproduces the model
identity, not necessarily the execution envelope bytes. Immutable persistence addresses both
identities and uses exclusive publication; no `latest` alias, overwrite, or database exists.

The accepted reusable Stage-8 solver uses Decimal. It is deliberately not changed or reused
inside binary64 fitting. The ticket-local Cholesky factorization supplies the required small
SPD solve and inverse. Near-optimum line search permits only an eight-ulp objective difference
with a strictly improved gradient (or an already-converged gradient); both final convergence
criteria still apply. No jitter, coefficient clipping or pseudo-inverse is used.

## Fixture/source reassessment boundary

Fixture adapter authentication caches complete serialized input, not mutable model references
or equality-normalized Decimal values. Public preparation returns independent validated copies.
A compact authenticated current-source assessment binds dataset, mode, competition, fixture
registry, season, cutoff, source identities, retrieval/usable times and due-result status.
It permits P0-degraded reuse of the latest sealed model without inventing a maximum model age
or claiming a current refit. The fixture bundle retains both the model cutoff and the newer
source-completeness assessment. Without reassessment, artifact-only inference conservatively
uses the original source retrieval timestamps. No fallback is computed inside fitting.
For LIVE_OBSERVED inference, the authenticated completeness assessment must be on the same
UTC calendar date as `as_of`: another D+2 result can become due at midnight even while source
retrieval age remains within 24/72 hours. Crossing midnight requires a newly built dataset
assessment; it does not require a refit when P0 permits degraded sealed-model reuse.

## Evaluation authority resolution

The evaluation scope is `B1-backtesting` in authority_manifest.json, not `A15-evaluation`.
Resolved decisions: ADR-DATA-004/005/006, ADR-EVAL-001/002/003/004/005/006 and
ADR-IMPL-001/003. DMFP-20 locators: lines 546–628, 2058–2225, 2758–2841.
DMFP-15 sections 0, 3, 4, 7, 10, 12, 26 and 27 control reconstructed classification,
cutoff-safe rolling origins, immutable inputs, proper metrics and no holdout retuning.
The B0–B5 ladder, sequential decision replay and prospective/calibration promotion gates
remain required before broader model/policy trust; 001A claims none of that acceptance.
Its narrow result is reconstructed football-prior reproduction and shadow capability only.

Authority byte identities at review:

- authority_manifest.json: `b780a757b922ab8fc70388de2651860f88908a96c5d91cc87bbabbdf555700ac`
- DMFP-15: `0feec95bb9a3fb31b5ccc504699681a8170d7c349c18accefc6e3047ab9a15ed`
- DMFP-20: `7ed484961cf81af1716db6daa51e6fa05ce2584c33bb04c1d59698e3bf934d72`

Real Stage-8 compatibility uses its existing balanced-market synthetic fixture and unchanged
public service. An additional H/D/A-only case (rates 2.024967/1.476651, targets .55/.25/.20,
uncertainty .05) triggers the inherited visible `PROJECTION_DID_NOT_CONVERGE` fallback under
the default Decimal context. This is preserved and tested, not counted as successful constrained
projection and not repaired by changing Stage-8 mathematics in this ticket. Compatibility is
not a universal-convergence claim.
