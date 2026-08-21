# GW1-PLY-002 calibrated candidate result

Artifact: `GW1_PLAYER_ROLE_PRIOR_CANDIDATE.json` /
`007e4d400d8f72eccc50541a9e9b385042bd3eb5d724b0b1d76e7cc69f42afb8`.
Its transformation code is commit
`92a2995143a67e78e98e2bd1b203d2c9f231fc6f`; it is explicitly
`CANDIDATE_NOT_ACCEPTED`.

## Coverage

- EPL 2017/18: 380 regular-duration matches, 512 exposed players and
  751,222.3277 reconstructed regulation minutes.
- No nonregular match was used. 48,033 event records without a reconstructed
  exposed player were excluded rather than allocated; two non-goalkeeper
  save-attempt records were excluded from goalkeeper saves.
- The artifact has 31 fields × 6 pools = 186 cells: 54 direct, 45 derived, 18
  role-pooled proxies, 6 generic fallbacks and 63 explicitly unsupported cells.
- It contains no Wyscout player identifier, player name, current FPL material,
  or current-player mapping.

## Tier-1 means per 90

| Pool | Nonpenalty goals | Broad Wyscout assists | Yellow | Red/second yellow | GK saves | Own-goal allocation weight |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FPL GK / tactical GK | 0.000658 | 0.003289 | 0.033553 | 0.000658 | 3.063816 | 0.005921 |
| FPL DEF | 0.035465 | 0.039918 | 0.153151 | 0.004930 | 0.000000 | 0.007157 |
| FPL MID | 0.106588 | 0.105590 | 0.161794 | 0.006153 | 0.000000 | 0.000499 |
| FPL FWD | 0.349220 | 0.120817 | 0.131262 | 0.005919 | 0.000000 | 0.001741 |
| League generic | 0.111718 | 0.073979 | 0.141430 | 0.004972 | 0.278965 | 0.003534 |

Non-GK save rates are explicitly position-not-applicable zero, not a smoothed
claim. The generic save rate exists only for the complete fallback interface;
the candidate supplies position rows for every valid current FPL position.

## Diagnostics and shrinkage

The leave-player-out position-versus-generic Poisson log-likelihood delta is
positive for nonpenalty goals (+425.7221) and broad assists (+108.4467).
Forward nonpenalty goal rate exceeds defender by +0.313755 per 90; midfielder
broad assist rate exceeds defender by +0.065672; defender clearance rate
exceeds forward by +2.113083. These are diagnostics, not an acceptance claim.

The transparent one-season moment estimates are 6.0933 (goals), 18.8028
(assists), 20.0383 (yellow), 48.5393 (red) and 0.4529 (saves) full-match
equivalents. None is adopted. `ROLE_MEAN_CALIBRATED = TRUE`, while
`SHRINKAGE_STRENGTH_CALIBRATED = FALSE`; the inherited 5/10/20,
3.5/7/14 and 15/30/60 candidate worlds remain active.
