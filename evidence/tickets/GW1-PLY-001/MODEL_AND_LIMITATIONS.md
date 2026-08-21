# GW1-PLY-001 candidate model and limitations

## Posterior-only empirical Bayes model

For each count rate, the candidate uses transparent Gamma-Poisson partial
pooling:

```text
theta_i,e ~ Gamma(mu_g,e * kappa_e, kappa_e)
Y_i,e     ~ Poisson(E_i * theta_i,e)
E_i       = approved completed historical minutes / 90
mean      = (Y + mu*kappa) / (E + kappa)
variance  = (Y + mu*kappa) / (E + kappa)^2
```

The candidate covers goals, assists, yellow cards, red cards and goalkeeper
saves. No-history players receive their pooled prior, never zero.

The values are expressly `TEMPORARY_CANDIDATE_PARAMETERS`, not an accepted
calibration:

| Field | Central candidate | Sensitivity |
| --- | ---: | --- |
| goals / assists kappa | 10 full-match equivalents | 5 / 20 |
| common events (yellow, saves) kappa | 7 | 3.5 / 14 |
| rare red-card kappa | 30 | 15 / 60 |
| recency half-life | 2 seasons | deterministic in all worlds |

The hierarchy is individual posterior, explicit current tactical role, FPL
position, then generic league prior. `UNKNOWN` is an explicit fallback; no
subjective automatic role classification is introduced. Real Wyscout role-prior
calibration, source rights, attribution, hashes and definition mapping remain
`ROLE_PRIOR_REAL_CALIBRATION = SEPARATE_CHECKPOINT`.

## Stage-9 adapter

Goal and assist propensities are:

```text
posterior per-90 rate × current role adjustment × bounded sparse price adjustment
```

They are normalized over the full current team into the existing
`PlayerAllocationProfile`. Stage-7 `p_start`, `p_appearance`, expected minutes
and exposure are not inputs to this construction. Existing Stage 9 then
dynamically renormalises over players actually on pitch and scales auxiliary
rates by simulated actual minutes.

Price is a position-local, monotonic, bounded sparse-evidence sensitivity only:
central `PRICE_OFF`, `PRICE_MODERATE` maximum 10%, `PRICE_STRONG` maximum 20%.
It cannot replace approved individual evidence and is not expected points.

Penalty responsibility is separate from ordinary `goal_share`. Active,
hash-bound human-reviewed primary/backup/candidate assignments override the
role prior only for `penalty_taker_share`; multiple active candidates remain
weighted uncertainty, never an arbitrary automatic 100% designation. The same
hash-bound override contract records tactical-role, major-role-change,
new-transfer-role and primary-material-set-piece evidence. A set-piece entry
is surfaced as a limitation only: Stage 9 has no separate set-piece allocation
channel, so it cannot silently alter open-play shares.

The emergency path builds all profiles from current FPL position, explicit
role/position priors, current price sensitivity and optional set-piece/penalty
overrides, with `DEGRADED_PLAYER_ALLOCATION = TRUE`. Individual historical
event evidence is explicitly inactive.

## BPS and defensive scope

Every required Stage-9 numeric field is populated from the pooled prior when
individual evidence is unavailable. This is not individual BPS reconstruction.
For the governed `config/rules/fpl-2026-27/bonus.yaml`, `being_tackled` is
`REMOVED`; the typed Stage-9 field remains for interface completeness but no
active negative coefficient is claimed. Successful-tackle detail and
non-penalty big-chance-save detail remain under-represented by the candidate;
the implementation does not compensate by changing unrelated rates.

Known profile limitations carry source level, fallback reason and prior version:

- `ROLE_PRIOR_REAL_CALIBRATION_SEPARATE_CHECKPOINT`
- `BPS_AUXILIARY_ROLE_POOLED_NOT_INDIVIDUAL_RECONSTRUCTION`
- `STAGE7_PARTICIPATION_OWNS_MINUTES_AND_ON_PITCH_ELIGIBILITY`
