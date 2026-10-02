# Accepted covariance audit, before sampling

Immutable audited parent: `605e404984ace1702d86dc69995cccc7ca7d8160`.
Exact file hashes are recorded by the checkpoint manifest.

- `team_strength_model.parameter_order`: `mu`, `global_home`, attacks for
  sorted UUID clubs 0 through N-2, then defences for those same clubs. Dimension
  is 2N, not 2N+2. The full historical registry contains 42 clubs (84 free
  coordinates); each artifact must determine its own fitted universe.
- `team_strength_numerics.reconstruct` and `_features`: the final sorted club
  is minus the sum of the other effects. These are free coordinates, not the
  redundant full constrained vector. Attack enters with +1, defence with -1;
  the global home effect enters only the home log rate.
- `objective`: Hessian of the negative time-weighted Poisson log likelihood
  plus the quadratic penalty. Each row contributes weight * exp(eta) * xx'.
  The attack and defence blocks include kappa * (I + 11'), because the final
  effect depends on every free coordinate. Kappa is 12 times the fixed
  unweighted team-score mean. Baseline and home terms are unpenalised.
- `_newton`: converged gradient infinity norm <= 1e-8 and relative objective
  change <= 1e-12. Information is recomputed at the converged free vector.
- `cholesky`, `inverse_information`: strictly SPD information, triangular
  solves for every identity column, then symmetric round-off averaging of
  the inverse. No jitter, damping of the final covariance, pseudoinverse or
  eigenvalue clipping. Full rank is required for every accepted fit.
- `_model_state`: persists both matrices as lower-triangle row-major decimal
  round-trip strings. Free mu/home coordinates are explicit; free attack and
  defence coordinates are the first N-1 sorted `effects` rows. Covariance rows
  follow exactly `parameter_order`, with log-rate coordinate units squared.
  No effective-sample-size rescaling or covariance reinterpretation is valid.

Conclusion: `LOCAL_LAPLACE_GAUSSIAN` around the penalised optimum, conditional
on the fixed cohort centres, hyperparameters, family and source evidence.
This is local penalised curvature, not an exact Bayesian posterior, a sandwich
frequentist covariance, or uncertainty in estimated cohort centres. It excludes
source, family and hyperparameter uncertainty. Joint sampling is supported.

New boundary validation requires exact order/dimension, finite coordinates,
structural reconstruction within the existing 1e-12 tolerance, SPD covariance,
and H*C identity residual <= 1e-8 (dimensionless binary64 multiplication error).
Serialized lower triangles are symmetric by construction. Generic matrix tests
allow relative/absolute 1e-12 asymmetry normalization only; material asymmetry or
non-PSD matrices fail. Zero-scale is an explicit research ablation, never an
automatic uncertain-coordinate replacement. No attack, defence or lambda is clipped.

Portability hardening preserves the immutable stored draw values and semantic
hash. Authentication rederives the joint construction with all lineage, policies,
IDs and weights exact, allowing regenerated free coordinates only within eight
binary64 ULPs of max(1, absolute target coordinate). This narrowly covers platform
libm roundoff; material changes fail. The stored artifact is never rewritten or
rounded to match a different platform. A one-ULP libm perturbation regression
passes, a 1e-5 perturbation fails, and Linux CI additionally exercises the frozen
Windows fit/draw inputs through the installed wheel. Existing market/prior-only
golden output hashes were retained when adding those immutable synthetic inputs.

NUMERICAL-VALIDATION.json records the 41-club/82-coordinate synthetic example:
H*C identity residual 1.993e-15, L*L' covariance residual 6.939e-18, minimum
Cholesky diagonal 0.04007177 and maximum draw identifiability residual 2.603e-17.
The separate 2026/27 benchmark has 42 clubs/84 coordinates. Both derive dimension
and ordering from their own authenticated accepted artifact.
