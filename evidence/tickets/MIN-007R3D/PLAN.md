# MIN-007R3D implementation plan

- Harden the stored conditional Decimal PMF to an exact high-precision simplex without changing public 12-decimal outputs.
- Canonicalize UUID-shaped `example_id` values before duplicate detection while preserving readable synthetic IDs.
- Enforce the full `MinuteConditionalPrediction` invariant at model validation and safe copy boundaries.
- Add focused adversarial probes for all required remediation cases, then run the 15-command acceptance ledger and frozen B/C/D/E oracles.
