# MQ000 separately versioned mathematical challenger

Owner scope: resume request section8; roadmap MQ000 prerequisite. Existing accepted
Stage12 RPS and Stage11 tactical validators stay byte-for-byte unchanged. Opt-in
pure tools live under scripts/, so package source/build identities are preserved.
No provider, model, database, activation, metric-registry or historical-score write.

`MQ000_FIXED_GRID_ORDINAL_RPS_V1` is the unnormalized lower-is-better sum of squared
CDF errors at all but the last category of one explicitly declared common target
grid. The full grid and its versioned digest accompany each score. It is an
ordinal-category score; grid spacing has no weight and this is not point-distance
CRPS. Changing the grid changes the metric contract and cannot be presented as
zero-probability PMF-key insertion. Comparisons require the same grid/digest.

The grid is nonempty, finite, strictly increasing and includes every supplied PMF
key and the observed outcome. A zero-probability observed category is valid;
an undeclared observed category fails rather than being clipped/interpolated.
A singleton grid permits only its one outcome and a unit point mass, scoring0.

Inputs accept exact Python int/Decimal only, reject bool/float/nonfinite values,
bound categories to10,000 and decimal digits/exponent magnitude to128/100. These
are computational input bounds for this version, not football rules or fitted
model parameters. Fractions preserve exact sums, products and normalization
independently of ambient Decimal precision. No silent renormalization occurs.

`MQ000_LOWER_INVERSE_CDF_SUMMARY_V1` derives the exact finite mean and p10/p50/p90
from the complete validated PMF. Quantiles are the least support value with
CDF>=alpha, including ties. Quantiles must be ordered. The mean has no ordering
constraint relative to quantiles; both upper and lower rare tails are legitimate.

Require adversarial and Hypothesis tests for negative/gapped/sparse supports,
out-of-positive-support observations, zero insertion/permutation, singleton,
strict grid/numeric bounds, low Decimal precision, CDF ties, rare-tail mean
outside central quantiles, and the expected-score propriety identity. Preserve
the exact original counterexamples and versioned historical metrics.

Mathematical basis: [Gneiting and Raftery2007 §6.4, equation49 and following
paragraph, journalp371](https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf).
For this finite domain the expected excess score equals the sum of squared CDF
differences; this is a direct algebraic derivation, not an empirical skill result.
Promotion or changes to accepted public/numerical contracts remain separate.
