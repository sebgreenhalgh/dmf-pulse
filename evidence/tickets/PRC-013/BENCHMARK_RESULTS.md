# Benchmark status

- P0 `NO_CHANGE`: implemented and independently golden-checked as the honest null.
- P1 regularized competing logit: implemented, deterministic, chronological and sealed.
- P2 recurrent latent pressure/hazard: implemented with repeat/opposite-event paths.
- Official FPL predictor, LiveFPL, Fantasy Football Fix and other approved external sources:
  stable observation/benchmark identities only; no automated capture and no performance claim.
- P3 GBDT: `DEPENDENCY_NOT_APPROVED`; P4: deferred.

Synthetic/replay tests validate contract behavior. They are not reported as real target-season
predictive performance.

Final main integration recognizes the official 2026/27 predictor's displayed/predicted progress
and categorical signals as first-party benchmark observations. Values above 100 remain progress,
not probabilities; the hidden threshold algorithm is still undisclosed, and automated capture
remains rights-blocked.
