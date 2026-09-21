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
