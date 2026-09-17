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

## A1.03 review remediation (pre-artifact checkpoint)

- Exact coherent information set: target GW5, finalized history GW1--4,
  rolling horizon GW5--7.
- Purpose-built root case: real canonical solves produce more than one current
  root action with a common candidate/action universe.
- Purpose-built continuation case: all four worlds retain one root action while
  STALE versus shadow worlds differ in real GW6/GW7 actions.
- All four solves report OPTIMAL with recommendation, hold baseline, transfer
  frontier and nonzero Stage-11 work counts.
- Pairwise classification, tamper rejection and actual reverse-order cache
  isolation pass. No manually altered optimizer result remains.
- Root artifact semantic SHA256:
  `f5ed1f8b64eb0270cca1a08de20bbbef67839de8d4d79d75f72cdab17a568cc1`.
- Continuation artifact semantic SHA256:
  `24583b60a8d047c59c0f5895ba923cb41904ed965b548bfefd58644b0f45f726`.
- Both artifacts canonically reproduce at implementation checkpoint
  `6612c386118a8d5c0b8be3da5c3b3b45210608aa`; timing measurements are
  explicitly non-semantic diagnostics.
- Final focused matrix: 93 R9B/Stage-9 tests, 221 exact Stage-10/Stage-11 tests,
  and all 185 private-v1 unit tests pass.
- Branch coverage across changed production modules is 91%: comparison 95%,
  adapter 92%, rolling 88%. The rolling file contains substantial inherited
  paths; all new Stage-11 work-disclosure lines execute in the real solves.
- Artifact/seal/adapter supplemental run: 10 passed in 239.71 seconds.
- Frozen-lock installed wheel imports the new contracts from site-packages and
  `dmf --help` passes outside the source tree. The initial unconstrained wheel
  environment resolved Typer 0.27.2 and failed; pinning the accepted lock's
  Typer 0.27.0 restored the required CLI behavior.
- Authority review remediation resolves every declared ticket scope exactly in
  `specs/manifests/authority_manifest.json`: A9 points, A10 one-GW optimizer,
  A11 decision bundle, and B2 multi-GW. Repository validation remains green.

## A1.02-CI-R1

- Reproduced the two failed legacy whole-file SHA guards exactly.
- Reconciled only their misleading inclusion of the intentional A1 service and
  rolling changes; all other historical provider/optimizer/rights digests stay
  exact.
- Horizon probe and rights approval tests: 102 passed.
- A1/R9B/rolling focused regression: 66 passed in 166.290 seconds.
- `src/dmf_pulse/**` is byte-identical to A1.02 parent
  `3b478e841fefa3d3f251275b59673367a6d5865c`.
