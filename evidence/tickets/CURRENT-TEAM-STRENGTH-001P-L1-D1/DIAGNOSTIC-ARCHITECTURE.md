# D1 safe transient diagnostic boundary

## Historical limit and authorization

Newest human-provided safe record: coarse stage `RUN_TWO_WORLD_COMPARISON`, reason
`TWO_WORLD_COMPARISON_FAILED`, FPL requests 12, Odds acquisition/request 1/1,
private attempt consumed, no retry, persistence false, production activation
false. These are user-reported historical facts, not reconstructed D1 telemetry.

Historical L1 failure localisation is unavailable under the old coarse boundary.
No frozen private context was retained; no exact historical exception is claimed.
The offline work-budget defect does not establish retroactive root cause.

The consumed approval and attestation are explicitly non-reusable. D1 rejects
the old approval before credentials/providers. No fresh approval, operator reset
switch or new live execution exists. Historical consumption is distinct from a
new blocked invocation's zero requests/unconsumed current attempt.

## Closed taxonomy and progress

`team_strength_diagnostics.py` owns strict/frozen extra-forbidden enums/model:
input validation, resolver validation, prepared Stage-7 validation, baseline
world, shadow world, world bindings, hard controls, player movement, fixture prior
comparison, decision materiality, sealing and timings (12 stages).

Reasons distinguish every major boundary and world Stage-8 invalid/BLOCKED.
Existing internal errors are recognized only by typed code and finite allowlist;
arbitrary message/class-name parsing is absent. Unknown codes become null.

Safe fields: stage/reason, allowlisted internal code/control name, failed world,
both worlds' started/completed booleans, optional bounded GW/fixture ordinal,
finite market coverage, Stage-8 state/error code and projected/prior-fallback
aggregate counts. A later failure cannot be attributed to the last successful
fixture: successful projection clears failure location.
Starting a new projection records location but no presumed outcome. Only the
existing caught-input-error handler marks INPUT_INVALID; an unexpected projector
exception retains safe location with generic world failure, not an invented
input-validation diagnosis. A prior successful outcome cannot carry forward.

Forbidden output: exception text/chains/class names, raw provider responses,
credentials, entry ID, manager state, private fixture/team/player identities,
player catalogues, market probabilities, score matrices and raw lineage hashes.
No diagnostic persistence or logger is introduced.

The scoped ContextVar is active only in the explicit two-world comparison and is
reset in `finally`, including nested calls. Ordinary service callbacks are no-ops.
Four observational notes surround the existing private Stage-8 block. Removing
those notes/import yields the exact immutable parent service AST. All other
Stage-8/9/10/11 numerical/request code remains unchanged.

The L1 terminal boundary revalidates the exact diagnostic type and raw fields
before serialization. This avoids Pydantic serializer warnings quoting a forged
field. Invalid diagnostics collapse to the old safe finite failure, never raw
text. Typed wrapping suppresses exception chaining in rendered tracebacks.

## Stage-8 classification

Real public Stage-8 tests cover baseline rates 1.613158/1.374561 and six candidate
ranges: strong home 2.6/0.65, weak home 0.7/2.35, balanced 1.5/1.3, entrant-like
0.9/1.85, low total 0.8/0.65, high total 2.6/2.1. All rates satisfy (0,8]. These
are synthetic realistic rate probes, not parameter-mixture inference.

Full H2H+totals, H2H only and prior only use the unchanged real service. Genuine
outer BLOCKED is distinct from accepted projection fallback. The known accepted
001A H2H nonconvergence returns outer PROJECTED with lower diagnostic DEGRADED,
`PROJECTION_DID_NOT_CONVERGE` and `NUMERICAL_FALLBACK_TO_PRIOR`. D1 does not relabel
it BLOCKED, claim fitted market convergence, alter numerical tolerances or retry.

At Decimal precision 28, the seven unique baseline/candidate priors yielded:
full market 7 PROJECTED; H2H only 6 PROJECTED and 1 DEGRADED prior fallback;
prior only 7 PRIOR_ONLY (all outer results PROJECTED). The paired matrix reuses
the baseline in each of the six cases. Specifically, the H2H-only low-total
candidate (0.8/0.65) uses the existing fallback while its baseline converges;
the other five candidate priors converge. This independently demonstrates a
prior-dependent compatibility boundary without claiming the historical cause.
The real private Stage-8 hook test also
exercises an accepted generated-fixture prior fallback before an injected later
failure, proving that it clears the failed-fixture location and counts fallback.

Scheduled range probes did not produce an outer numerical BLOCKED case. Explicit
POSTPONED/CANCELLED/ABANDONED cases exercise the real legitimate BLOCKED boundary.
Totals-only future evidence uses the actual private market builder and remains
H2H_UNAVAILABLE with empty constraints (prior-only), not newly activated totals.

The earlier successful private service accepted prior fallback; D1 preserves that
decision behavior and exposes aggregate fallback diagnostics on failure. No
standalone Stage-8 compatibility change or future design decision is invented.
