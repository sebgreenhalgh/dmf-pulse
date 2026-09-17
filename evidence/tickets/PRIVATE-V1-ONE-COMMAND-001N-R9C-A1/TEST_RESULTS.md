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

## A1.03

- Four-world canonical rolling regression: PASS (2 tests; one shared real
  four-world Stage-9 -> Stage-10 -> Stage-11 run).
- The synthetic probe produced comparison hash
  `ac9a238ef8fd37750eec6680ae29e1826c23aa838b7b81747ce57e6b0a9b361d`.
- All six pairwise world comparisons were `ROBUST` for this deliberately small
  candidate universe; Stage-7/8 context/distribution, scenario identity and
  candidate-screen hashes were exact-equal. This is an observed synthetic
  result, not an assertion about a live decision.
- Classification-contract tests separately exercise `ROBUST`,
  `ROOT_SENSITIVE`, and `CONTINUATION_SENSITIVE` without constructing another
  optimiser or projector.
- No cross-world plan re-evaluation is reported: the accepted rolling service
  has no sealed public evaluation seam for an already-legal fixed policy, and
  A1.03 must not recreate Stage-11 evaluation outside that service.
- A1 seam/adapter/four-world focused regression: 13 passed in 161.56 seconds.

## A1.02-CI-R1

- Reproduced the two failed legacy whole-file SHA guards exactly.
- Reconciled only their misleading inclusion of the intentional A1 service and
  rolling changes; all other historical provider/optimizer/rights digests stay
  exact.
- Horizon probe and rights approval tests: 102 passed.
- A1/R9B/rolling focused regression: 66 passed in 166.290 seconds.
- `src/dmf_pulse/**` is byte-identical to A1.02 parent
  `3b478e841fefa3d3f251275b59673367a6d5865c`.
