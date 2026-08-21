# GW1-PLY-002 calibration method

For regular-duration EPL 2017/18 matches, the builder starts each listed XI at
0–90 regulation minutes, applies each recorded substitution (clipped at 90),
then shortens the interval for a Wyscout red/second-yellow event. Extra-time or
unusable-formations are excluded rather than treated as a 90-minute
appearance. Counts are divided by this reconstructed exposure.

Count fields use a pooled Jeffreys Gamma-Poisson estimate:

```text
mean     = (events + 0.5) / exposure_90
variance = (events + 0.5) / exposure_90^2
```

Pass completion uses a Jeffreys Beta-Binomial aggregate. Artifact cells retain
the raw rate, event count, exposure, estimate, variance/normal-approximation
interval, mapping quality and fallback level.

`players.json` supplies only Goalkeeper, Defender, Midfielder and Forward. GK
is therefore the sole direct tactical-role prior. CB, FB_WB, DM, CM, AM,
WINGER and CF deliberately resolve through FPL-position fallback, not an
inferred historical formation or player reputation.

One-season moment kappa estimates are diagnostic only. The candidate retains
GW1-PLY-001 central/low/high worlds (10/5/20 for goals and assists, 7/3.5/14
for yellow/saves, 30/15/60 for red) because the historical sample is one
season with coarse roles and unmodelled player/club context.
