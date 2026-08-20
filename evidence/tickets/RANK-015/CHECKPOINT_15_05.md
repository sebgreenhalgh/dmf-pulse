# RANK-015 checkpoint 15.05 assurance

## Scope

Checkpoint 15.05 implements the rights-gated synthetic overall-field rank
approximation. It uses weighted representatives and exact integer represented
populations; it does not scrape or expand a mass manager population.

## Published capability

- Remote capability SHA: `62f1828edcfbd0569dbf76fc93e241f2db95094d`.
- Synthetic or repository-approved representative populations only.
- Explicit rank bands, representative counts and total-population reconciliation.
- One target manager represented exactly once and prohibited from the opponent population.
- Shared Stage-9 scenario-set, raw-projection and manager-multiplier lineage.
- Cumulative points, Gameweek points, transfer hits and counted-transfer tie state.
- Weighted rank PMF, expected/median/percentile rank, P(target) and rank-one diagnostic.
- Concentration, entropy, maximum-share and effective-representative diagnostics.
- Explicit known-truth versus weighted-approximation status.
- Rights, provenance, source-bundle and upstream-hash lineage.
- Explicit prohibition of mass scraping, final-rank hindsight and definitive overall-win claims.

## Independent exhaustive oracle

`tests/support/synthetic_field_oracle.py` imports no production synthetic-field
simulator. The tiny known-truth fixture is enumerated independently and the
production distribution, outcome ranks, PMF and P(target) must match exactly.

## Adversarial coverage

The checkpoint and pre-15.06 hardening tests reject:

- duplicated representative identities or manager identities;
- representative or band weights that do not reconcile;
- target duplication inside the represented population;
- overlapping, unsorted or out-of-population rank bands;
- post-cutoff generation and final-rank hindsight surfaces;
- rights-invalid populations and rights/basis relabelling;
- mismatched football scenario, raw projection or manager multiplier lineage;
- noncanonical PMFs, outcomes, percentile maps and P(target);
- synthetic known-truth disagreement with the independent oracle;
- result, population and distribution hash tampering.

## Focused verification

Original published capability matrix:

```text
23 passed
```

Current hardened synthetic matrix, including adversarial contract guards:

```text
34 passed in 3.36s
raw branch coverage: 98.684211% (150/152)
combined line/branch coverage: 99.249531%
```

Ruff focused: `PASS`.
Strict mypy for the Stage-15 production package: `PASS`.
`git diff --check`: `PASS`.

## Status

`COMPLETE_REMOTE_PENDING_INDEPENDENT_REVIEW`
