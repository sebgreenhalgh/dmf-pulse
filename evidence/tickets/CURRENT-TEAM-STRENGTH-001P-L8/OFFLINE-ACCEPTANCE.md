# L8 Phase A offline acceptance

## Authority and public readiness

- Exact current L8 approval/attestation accepted; L1–L7 remain permanently
  consumed. Wrong, mixed, malformed and unknown pairs are rejected before
  credentials or provider transports.
- Standing official-FPL purpose independently checked adequate for one
  low-volume operator-initiated read-only frozen-state observation; FPL and
  OpenFootball rights files are byte-identical to the D7 parent.
- Odds account, geography, terms, capabilities, unresolved rights and zero
  retention are unchanged. Only the four approval-purpose metadata fields
  changed; the exact new profile SHA is
  `0a66bb6fa18f9533d93208a95aca5fec2834227a8615f5e36674812a57025fff`.
  The prior L7 purpose SHA is rejected for L8.
- September 30 public OpenFootball readiness is `LIVE_OBSERVED`, `FRESH`,
  `FRESH_FIT`: 50/50 due fixtures scored, `missing_due=0`, 380 current fixture
  registrations, 42 fitted clubs, retained Hessian and local covariance.
  Commit `e6744429ee395bc86f247348c6184bb08d4eb361` remained public HEAD
  on recheck; the new cutoff changed decay weights, so sealed reuse was not
  claimed. Readiness SHA is
  `4722ab116b48f2bb83466f6d6c07bbee2ff834c1680092b1c11f55b72eff80d8`.

## D7 exact policy-capacity oracle

- Four offline repository-owned synthetic reruns were made: governed and
  10-million reference caps for baseline-like and shifted-shadow-like
  projection orderings. Evidence semantic SHA:
  `856fbae0d35a58f4ac0858f020a06e27e4c4bf7b14407170c62c187b1d8325e8`.
- The unchanged governed policy-v2 capacities distinguish generated policies
  `2097152`, retained Pareto candidates `786432`, and legal actions `2097152`.
  Neither candidate scope nor exactness was relaxed.
- Baseline-like: 1,432,370 generated policies and 1,432,370 legal actions;
  governed and high both `SUCCESS` with accepted decision SHA
  `3fb1df08c27e063869f8922f71f2634b11c907fa3f8385325835d3f2769403bb`.
- Shifted-shadow-like: 1,432,641 generated policies and 1,432,370 legal
  actions; governed and high both `SUCCESS` with accepted decision SHA
  `f5d4df2085e46bd4d7084e278c157f1ac6ca1a0f3d145226da43d9af968dcda8`.
- Full decision semantics, including recommendation, no-transfer baseline,
  root counterfactual, transfer-count frontier, future policy and utilities,
  are identical between governed and high caps in both worlds. Four raw-probe
  hashes and the sealed evidence hash were independently recomputed.

## Regression and quality

- Focused L8 authority, rights, CLI and wrapper population: 146 passed.
- L8 exact authority and capacity-evidence population: 77 passed.
- Complete private-v1 population, including D1–D7 diagnostics, ordinary
  one-command, generated two-world success and rolling comparisons: 661 passed,
  1 deselected in 3,856.55 seconds. The single deselection was the dedicated L8
  oracle-evidence test, separately passed in the 77-test L8 population above.
- Generated two-world Stage 8→11 success slice: 1 passed.
- Five accepted offline 001P cases A/B/C/D/E: all passed with zero provider
  requests.
- Public team-strength/OpenFootball/Stage-8/Stage-11 population: 985 passed.
- Stage-9/Stage-10 populations: 474 passed.
- Ordinary one-command ingestion regressions: 8 passed.
- Inherited D7 evidence/script tests: 4 passed.
- Ruff format/check: PASS; strict mypy: 313 source files, PASS.
- Frozen all-group dependency sync: PASS, 40 packages checked.
- Wheel/sdist build and clean external installed-wheel authority/diagnostic
  smoke: PASS, provider calls 0.
- Specification authority validation: 94 decisions, 22 documents, 19 scopes,
  PASS. Repository validator after active-manifest refresh: PASS, zero errors.
- Test configuration validation and sanitized display: PASS; `dmf doctor`:
  HEALTHY (optional NVIDIA timeout nonblocking).
- First-party secret scan: PASS, zero findings. `git diff --check`: PASS.

Mandatory exact-SHA CI runs after publication; it is not represented here as an
offline run.
No FPL or Odds request, credential inspection, private observation, retry,
private-data persistence or production activation occurred in Phase A.
