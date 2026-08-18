# Independent Sol review findings

Review baseline: `a2fdeea7b6514cb8f37b2f687d892998a1422973`, directly above immutable
Stage-12 parent `ce7fe8f4354d95a477afcf6eed45f63cf0ab772e`. The withdrawn stale identity
`0dfdb83af82b7f5b42602d37f83fc53170c3b125` was not reviewed.

All valid P0/P1 findings and all identified material P2 findings were remediated. No unresolved
P0/P1 remains. `tests/unit/prices/test_independent_review_remediation.py` contains the principal
new regression oracles, with related contract updates in the existing price suites.

| ID | Priority | Root cause | Remediation and regression |
|---|---|---|---|
| SOL-PRC-001 | P0 | Inference did not prove that model and calibration training cutoffs preceded the forecast cutoff. | Prediction now blocks future-trained sealed artifacts; future-model and future-calibrator regressions pass. |
| SOL-PRC-002 | P0 | ACT/WAIT accepted caller policy/mode claims independent of projection lineage and did not verify the projection seal. | Projection integrity, dataset mode, configuration hash and activation status are verified before utility ranking; bypass/tamper regressions pass. |
| SOL-PRC-003 | P1 | Model configuration/schema/version and recurrent-state version could drift from active policy. | Exact configuration hash, model identity, feature schema and state version binding are enforced and tested. |
| SOL-PRC-004 | P1 | Repeated identical payloads were discarded even though their observation time carries elapsed-velocity information. | Repeated observations are retained and marked `DUPLICATE_SNAPSHOT`; timing/zero-flow regressions pass. |
| SOL-PRC-005 | P1 | Boundary logic checked only whether the current price equalled a bound, so configured multi-unit steps could escape support. | Bounds now test the complete next step; multi-unit boundary regression passes. |
| SOL-PRC-006 | P1 | Simulated recurrent state allowed time reversal. | Transitions require UTC and nondecreasing `as_of`; time-reversal regression passes. |
| SOL-PRC-007 | P1 | A sealed aggregate price calibrator did not independently prove its nested Stage-12 calibrator seals. | Seal and apply paths verify all three nested artifacts; nested-tamper regression passes. |
| SOL-PRC-008 | P1 | Selling/scenario adapters accepted closed ownership spells or a spell for another player. | Active-spell and player-identity checks guard exact Stage-11 reuse; adversarial regressions pass. |
| SOL-PRC-009 | P1 | Projection lineage did not preserve explicit source-ID→semantic-hash pairing or bind model, calibration, path and configuration artifact hashes. | Lineage now pair-canonicalizes sources and carries/validates all artifact identities; incomplete/noncanonical/pair-preservation regressions pass. |
| SOL-PRC-010 | P1 | Lexical ID order could beat a later system-time correction at the same valid time; cycle IDs and correction predecessors were under-validated. | Bitemporal selectors, unique identities and known predecessor checks are enforced; same-valid-time correction regression passes. |
| SOL-PRC-011 | P1 | Service ingress silently coerced binary-float integer inputs and other scalar identities. | Strict Pydantic adapters replace permissive scalar coercions; float-to-price regression passes. |
| SOL-PRC-012 | P1 | Rehydrated price-path artifacts weakly checked scenario transitions, bounds, horizon order and aggregate probabilities. | Artifact validation reconciles exact step transitions, final PMF, any/multiple-event probabilities and scenario uniqueness; tamper regressions pass. |
| SOL-PRC-013 | P1 | Rehydrated update-cycle and early-transfer artifacts could encode contradictory event/interval or decision/activation summaries. | Cross-field invariants now enforce integer transitions, interval semantics, complete-utility selection and fail-closed activation. |
| SOL-PRC-014 | P2 | Synthetic numerical policy values were identified only indirectly by the configuration name. | Configuration and validation output now state `POLICY_CONFIGURATION`, `PROVISIONAL_MODEL_PARAMETER` and `SYNTHETIC_REFERENCE`. |
| SOL-PRC-015 | P2 | Evaluation reports omitted an explicit price horizon and no-change calibration diagnostics. | Reports are single-horizon and include no-change calibration status/intercept/slope; mixed-horizon regression passes. |
| SOL-PRC-016 | P2 | Multiple-rise/fall Gameweek probability ignored event counts already present in recurrent state. | Exact path aggregation includes initial Gameweek counts; carry-in regression passes. |

No P3 code finding required remediation. Review of external benchmark contracts, rights controls,
no-scraping boundaries, P0/P1/P2 model roles, Stage-12 inner/outer calibration isolation, Stage-11
selling-price reuse and hidden-algorithm language found no additional defect after remediation.
