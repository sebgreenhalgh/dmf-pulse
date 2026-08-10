# MIN-007R4 implementation plan

- Replace fixed-precision stored-PMF validation and correction with exact coefficient/exponent arithmetic.
- Replace fixed-precision candidate START+BENCH validation with exact integer comparison against one.
- Add adversarial regressions for 1E-300, 1E-1000, tiny half-sum excess, ambient precisions 10/28/60/256, safe boundaries, nonfinite weights, and model-copy revalidation.
- Preserve the frozen precision-60 calculations, projections, and B/C/D/E identities.
- Run the 15-command acceptance ledger and leave one bounded commit with a clean tree.
