# R9C-A1 acceptance

The normal rolling service has no injected resolver and retains the literal
governed stale-binding path. The internal resolver exists solely for synthetic,
offline shadow comparison. It binds only the already compiled R9B worlds
`CENTRAL_TEMPORARY`, `LOW_SHRINKAGE`, and `HIGH_SHRINKAGE`; `STALE` remains the
normal no-resolver baseline.

Injected profiles require exact Stage-7 identity/team coverage and separate
non-active provenance. Only R9B's existing assist, yellow-card, red-card and
goalkeeper-save profile fields may differ.

## A1.03

The offline synthetic comparison invokes `PrivateV1RollingRecommendationService`
four times: literal stale construction with no resolver, then each already
sealed R9B world. Each call has fresh service/resolver state. The comparison
requires exact equality of Stage-7 contexts, Stage-8 distributions, scenario
IDs/weights and rolling input identity before it records Stage-9/Stage-11
differences. Candidate-screen scope is separately hashed and disclosed.

`scripts/compare_r9c_a1_three_gw_shadow.py` is repository-only, no-argument,
synthetic output for manual review. It makes no network request and does not
write a result file. It neither exposes a normal world selector nor changes
the stale active path.

## A1.02-CI-R1

The inherited R8A/R8B static digest guards freeze only their still-unmodified
provider, optimiser, executable and rights surfaces. They explicitly exclude
the two A1-owned files whose behavior is protected by A1 semantic-invariant
tests: `private_v1/service.py` and `private_v1/rolling.py`.
