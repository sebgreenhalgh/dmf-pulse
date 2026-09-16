# R9C-A1 local test results

All evidence is local, synthetic and offline. No provider path, credential,
live snapshot, persistence, fitting or activation was used.

- A1.01 allocation seam: 8 passed, including default deterministic equality,
  exact-coverage failures, provenance binding and reverse-order isolation.
- A1.02 adapter: 3 passed, including supported-field-only substitution,
  deterministic resolution, fail-closed missing identity and Stage-9 movement.
- Combined rolling/R9B/A1 regression: 62 passed in 156.902 seconds.
- Ruff, strict mypy, repository validator and repository-manifest integration:
  passed.

The full four-world three-GW Stage-11 comparison was deliberately not run.

## A1.02-CI-R1

- Reproduced the two failed legacy whole-file SHA guards exactly.
- Reconciled only their misleading inclusion of the intentional A1 service and
  rolling changes; all other historical provider/optimizer/rights digests stay
  exact.
- Horizon probe and rights approval tests: 102 passed.
- A1/R9B/rolling focused regression: 66 passed in 166.290 seconds.
- `src/dmf_pulse/**` is byte-identical to A1.02 parent
  `3b478e841fefa3d3f251275b59673367a6d5865c`.
