# R9B architecture and limitations

## Isolation and numerical contract

Three new, explicitly invoked package modules implement immutable prior/posterior
contracts, pure compilation and aggregate diagnostics. The ordinary private command,
current acquisition, R9A, Stage 7-11, R7, R8B, V3, rights, dependencies and source-type
contracts are unchanged. The historical resource is loaded once on explicit demand;
only that immutable historical resource is cached, never current player history.

The donor is resolved through the existing `CurrentGwPlayerPriorBinding` and
reconstructed with its existing policy at the boundary. Donor personal history is
not current-player history. Each likelihood/output uses its current identity and
separate current-history entry hash. All current catalogue entries are required,
including absent/new players. No old club membership is inferred.

For each world and component, historical mean m and variance v imply beta=m/v and
alpha=m*beta. Apply observed events y and minutes/90 once:
mean=(alpha+y)/(beta+t), variance=mean/(beta+t). Historical kappa is already inside
the historical posterior and is NOT reapplied. No current-data fit, epsilon,
world selection or newly invented prior strength occurs. Degenerate applicable
priors preserve the stale field with typed status. Outfield saves are structural
zero. Goal posteriors are a diagnostic channel, structurally absent from profile
update construction.

Only assist propensity, yellow/red per90, and GK saves per90 can change in shadow.
Assist propensity multiplies stale weight by posterior/historical rate, WITHOUT
future expected minutes. Actual Stage-9 allocation continues to normalize eligible
on-pitch weights. Team TV is separately normalized over the current catalogue;
it is descriptive, not an unconditional probability or a team-history assertion.

## Missingness and exposure

The exact already-acquired finalized/data-checked prior window is reused (maximum
12 GWs), with source/cutoff and bootstrap reconciliation rechecked from facts.
GW aggregates are never fixture observations. Missing player rows do not contribute
zero. A new player's fully published available rows may update a rate, while its
full-season reconciliation remains explicitly not applicable. Missing statistic OR
minutes in any available row blocks that field's update, retaining the stale value.
No rows retain unavailable counts rather than a zero ability estimate.

Zero-minute discipline rows are excluded, with excluded row AND event counts.
Positive goals/assists/saves at zero exposure fail closed. Non-GK save evidence
must agree with structural zero. BPS/bonus are diagnostic outcomes; CBI remains a
single combined count. Tackle/recovery/CBI comparisons disclose provider-definition
mismatch and are not empirical calibration of donor components.

## Source integrity and retained evidence

The compact resource is generated solely from immutable local historical Git
objects. All three canonical posterior digests are recomputed, all 1797 ordered
donor/world rows are checked, and the resource is pinned to its original digest.
Mean/variance/source/world tampering fails even if a caller recalculates a seal.
The generator requires those Git objects; the wheel contains the sealed compact
resource and needs neither Git nor the historical full artifacts at runtime.

R9A source hashes establish deterministic integrity/lineage, not cryptographic
provider authentication. The compiler validates source relationships without raw
bodies. It cannot independently prove a provider receipt time absent from R9A's
per-GW contract. The operator probe bounds the entire acquisition, including the
last live response, with a five-minute cutoff window. The compiler itself is pure.

Only historical and repository-generated synthetic evidence is committed. The
operator probe prints aggregates and no names/player rows, raw bodies, manager
facts or credentials. Failures use a fixed safe vocabulary. It never calls Odds,
Stage 7-11 or a recommendation. It was NOT run with live inputs during this task.

## Statistical limitations

Temporary kappa worlds are sensitivity experiments, not calibrated truth. Current
official FPL assists and historical broad assists differ semantically. Goals lack
non-penalty decomposition. No unsupported defensive/BPS component is updated.
Model movement is not improved real-world accuracy; the recorded Stage-10 case
does not change the selected squad, captain or XI. Four observed GWs are an operator
supplied live observation, not a newly independently measured dataset in R9B.
Actual live 659-player binding and its assignment breakdown remain unmeasured here.

The Stage-9 ablation uses an explicit reference-only rules fixture and generated
synthetic inputs. The separate Stage-10 experiment uses the existing VERIFIED
target-season rules in TEST mode, two declared legal squads and frozen synthetic
fixtures, with no price/hit/FT optimization. R9C still needs a full rolling shadow
adapter; no missing rolling result is represented as a false 'unchanged' outcome.
