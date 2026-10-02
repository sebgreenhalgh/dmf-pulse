# Independent adversarial review

Reviewer: fresh read-only `/root/independent_review` agent, 2026-10-02.
The following is the reviewer's final response, preserved verbatim.

`CLEAR_FOR_CURRENT_TEAM_STRENGTH_001U_SHADOW_PROSPECTIVE_EVALUATION`

No unresolved P0/P1 or material P2 finding remains in the reviewed U07 scope.

1. **Is L8 permanently consumed? Yes.** `team_strength_live_authority.py:CONSUMED_APPROVALS` contains L1–L8. Historical L8 requests fail with `ConsumedL1ApprovalError`; closure, L1 and installed-wheel tests verify this.

2. **Is there no current live authority? Yes.** `CURRENT_APPROVAL` and `CURRENT_ATTESTATION` are `None`. Historical compatibility constants do not authorize execution. No L9 or reset exists.

3. **Was no private provider accessed? Yes, within the reviewed 001U execution evidence.** Runs are offline/public/synthetic; external-wheel checks block sockets and report zero provider calls. This review performed no credential inspection or provider access.

4. **Is the covariance interpretation scientifically correct? Yes.** It is inverse full penalised observed-information curvature in the accepted reduced coordinates, labelled `LOCAL_LAPLACE_GAUSSIAN`. It remains conditional on the cohort, hyperparameters, model family and source vintage; no exact Bayesian posterior or sandwich interpretation is claimed. See `COVARIANCE-AUDIT.md` and `team_strength_numerics.py:objective/inverse_information`.

5. **Are parameter draws joint? Yes.** `team_strength_parameter_draws.py:joint_parameter_draws` applies the full joint Cholesky factor. Fixture identity is absent from parameter generation; each draw supplies one shared team-strength world across fixtures.

6. **Are uncertainty identities separated? Yes.** `NestedDrawIdentity`, `outcome_identity` and `ParameterMixtureStage8V1` retain structural, parameter and outcome identity distinctions. Diagnostics explicitly distinguish parameter marginalisation from downstream aleatoric outcomes. No new Stage 9–11 parameter-world solve programme is claimed.

7. **Does zero uncertainty reduce exactly to the plug-in shadow? Yes.** Zero-scale mixture and Stage-8 tests verify exact plug-in outputs for both market-backed and prior-only fixtures.

8. **Is the mixture coherent? Yes.** `team_strength_mixture.py:build_parameter_mixture` forms weighted conditional Poisson distributions with finite, nonnegative, normalised probabilities. Validators reconcile rate means, epistemic variance, predictive variance and truncation diagnostics. Invalid rates fail without clipping.

9. **Is ordinary Stage 8 unchanged? Yes.** The ordinary `football_events/service.py` is unchanged. The separate research projection uses the same market constraints and reconciliation machinery. Relevant regression populations passed.

10. **Is the plug-in shadow unchanged? Yes.** The accepted model, fitting numerics and adapter are unchanged. Canonical parent replay preserves exact underlying comparisons, player movements, fixture outputs and every retained summary field.

11. **Is parameter mixture shadow-only? Yes.** Distinct research schemas and families require `RESEARCH_ONLY` and false production activation. No ordinary/default resolver switch or silent plug-in substitution was introduced.

12. **Is screen confounding measured safely? Yes.** `team_strength_comparison.py:_run_screen_metrics` measures actual allowed-transfer populations and node eligibility, with overlap, additions/removals and protected-candidate retention. Safe summaries remove raw transfer, captain and vice identities.

13. **Is exact cross-screen decomposition off by default? Yes.** Its explicit status is `OFF_BY_DEFAULT_NOT_IMPLEMENTED`. No additional private-live cross-screen solves exist.

14. **Is public prospective evaluation time-safe? Yes.** `team_strength_prospective.py:validate_frozen_forecasts/score_public_team_forecasts` binds the actual training dataset and source vintage, excludes target outcomes from training and source evidence, enforces origin/freeze availability and conservative date-only scheduling, and requires post-freeze, D+2-eligible outcomes.

15. **Can reconstructed data masquerade as `LIVE_OBSERVED`? No.** Forecast mode must match authenticated model/training mode. Temporal lineage remains validated; calibration rejects mixed modes and retains source/report identities.

16. **Is private prospective persistence prohibited? Yes.** `team_strength_prospective_store.py:persist_public_forecast` accepts only the strict public forecast contract. Private/non-forecast inputs fail with `PRIVATE_PROSPECTIVE_STORAGE_NOT_AUTHORIZED` before filesystem access. Public publication is immutable, content-addressed and collision-checked.

17. **Is there automatic production activation? No.** Activation fields are literal false; neither scoring, calibration nor observation counts activate a model.

18. **Are promotion claims limited appropriately? Yes.** Historical L8 establishes decision materiality, not accuracy. Synthetic proper scores establish mechanisms only. Eight promotion-evidence categories and a later human decision remain mandatory. Convergence selected no operational draw count.

19. **Are performance claims measured? Yes.** `PERFORMANCE.json` records draw-count scaling, 380-fixture construction, Stage-8 comparisons and prospective scoring. Memory is explicitly traced Python allocations, excluding setup/caches—not RSS. Concurrent regression load is disclosed; no private Stage-11 or live deadline claim is made.

20. **Is rollback straightforward? Yes.** Stop explicit mixture/prospective research calls and retain the unchanged ordinary baseline/plug-in paths. Preserve U.01 closure; restoring historical live L8 authority is not a rollback step.

Resolved review findings covered Decimal draw weights, actual screen populations, prospective temporal/source leakage, calibration provenance, score-contract validation and stored-draw portability. Evidence-builder safety and failure-accounting concerns were also corrected.

Verification includes 105 focused tests, seven canonical/D7 repair tests and all 44 L1 tests passing. The broad run recorded 2,126 passes and exactly seven historical expectation failures; the complete repair populations resolve those seven. I independently verified all 19 recorded command-log hashes, the three research-artifact semantic hashes and benchmark source hashes.

This verdict covers the reviewed source and local evidence. Capped-pack verification, final local/remote SHA equality and exact-SHA mandatory CI remain publication gates. **It does not authorize production activation.**
