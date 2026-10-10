# P02+ prospective protocol

The user-approved CURRENT-TEAM-STRENGTH-001V-PROTOCOL contract is subordinate to
the A3/A8/B1 authority bundles in `specs/manifests/authority_manifest.json`.
ADR-DATA-004/005/006 require usable-time, immutable information bundles and mode
separation. ADR-EVAL-001/002/004/006 require prequential freezes, separate
operations/decision evidence, proper scores/calibration and locked confirmation.
DMFP-15 sections on block/cluster resampling and paired comparisons govern the
new reporting layer. Existing 001U scoring definitions and model files are frozen.

The packaged content-addressed protocol becomes effective at P02. P01 is the
pre-existing PROSPECTIVE_PILOT_COHORT in EVALUATION_EPOCH_001, with its original
forecast/bytes and P01_PILOT_LONG_LEAD class. It is never pooled with standard
cadence evidence. Its earliest potential score remains 2026-10-14T00:00:00Z,
subject to every actual played date, FULL_TIME and D+2 eligibility. No P01 outcome
is acquired or used in this ticket.

Select the next ten unassigned authenticated unscored EPL fixtures, ordered by
date then canonical ID, strictly after the UTC freeze date. A partial cohort is
allowed only when the authenticated schedule has fewer eligible remaining rows.
Assignments never change when dates move. The target is 12:00 UTC two calendar
days before the earliest selected date; the inclusive execution window ends six
hours later. Both forecast origin and actual frozen_at must be inside that window.
Misses are retained, consume their intended cohort ID and cannot be backdated.
The next valid opportunity is recomputed as dates advance, without hand-skipping
the first eligible fixtures; expired windows remain operational evidence.

The primary paired comparison is plug-in minus league baseline exact-score log
loss: negative favours plug-in. Secondary metrics retain all 001U team-count log
loss, goal RPS, three 1X2 Briers, two clean-sheet Briers, totals Briers at 0.5 to
5.5, and home/away goal biases. Mixture minus plug-in remains exploratory.
Only the accepted 2048-draw seed-23 scale-1 research policy is allowed. No
operationally converged draw count or production challenger is claimed.

Aggregation keeps every fixture, cohort and compatible cumulative population;
paired means use exactly the same fixture IDs. Populations split by epoch, mode,
draw policy and pilot/standard lead-time class. Primary uncertainty uses 4,096
whole-cohort resamples with replacement, retaining every paired fixture in each
selected cluster, fixed SHA256 counter stream and nearest-rank 2.5/97.5 percentiles.
The ratio of resampled loss sum to fixture count preserves partial-cohort weights.
At least ten complete cohorts in a population are required; otherwise report
INSUFFICIENT_PROSPECTIVE_COHORTS_FOR_STABLE_INFERENCE. These are descriptive
intervals, not sequential hypothesis tests or promotion cutoffs.

Calibration uses the existing intercept/slope machinery with event residuals,
Brier, fixture/cohort counts and the forecast-origin sampling warning. Fewer than
ten cohorts is explicitly insufficient for stable interpretation. Promoted-team
involvement comes solely from `TeamEffect.is_forecast_entrant`, authenticated
against existing memberships. Date-move subgroups are outcome-timing diagnostics,
not features or pre-freeze selection inputs. No probability-band subgroup is added.

Administrative interim reviews occur once at five and ten fully scored standard
P02+ cohorts within the active evaluation epoch. P01 is retained and reported
separately; it does not advance the standardized-cadence checkpoint count. Each
new epoch starts its own checkpoint count, preserving all historical evidence,
regardless of results. They retain misses/failures, report all predeclared metrics,
calibration, subgroups, methodology integrity and valid uncertainty. Cohort scoring
is allowed; cumulative evidence access is restricted to these declared reviews.
Neither checkpoint changes the model or satisfies a production promotion gate.

Any change to methodology, metric, subgroup or evaluation policy requires an
explicit amendment ticket, a new protocol version and a new evaluation epoch.
Time-safe normal refits change numerical estimates, sources and time weights
within the existing epoch. Confirmatory populations never mix epochs. The
code_sha256 is the SHA256 of a canonical accepted-methodology code manifest
containing the exact parent Git SHA and source file hashes, not a relabelled Git
SHA1 or a self-referential protocol implementation commit hash.

The eight 001U promotion categories remain mandatory and sufficiency is a separate
later human decision. L8 is decision materiality, not model accuracy and does not
automatically satisfy downstream decision evidence. No score, confidence interval,
count or calibration result can activate production. Strict public schemas reject
private/provider/manager/player fields; retained artifacts remain private internal
evidence under the unchanged public-source rights gate, not public redistribution.
