# MIN-007D implementation plan

- Add typed Decimal minute-prior and conditional-PMF models in `availability/minutes.py`.
- Fit frozen position/role START and BENCH priors from the accepted training dataset.
- Implement cutoff-safe target-team history selection, all-row recency ages, conditional weighting, and exact Decimal normalization.
- Add focused unit, property, and golden coverage for frozen canaries, fresh players, mixed weighting, GK concentration, 65-minute BENCH evidence, invalid inputs, and deterministic behavior.
- Run the 15-command acceptance ledger, record factual evidence, commit exactly once, and verify a clean tree.
