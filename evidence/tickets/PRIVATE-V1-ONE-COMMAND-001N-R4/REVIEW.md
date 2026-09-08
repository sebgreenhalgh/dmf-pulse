# Scope and correctness review

Parent `47215656bac92d0ef72077b79e179a8c001915bc` passed full CI `34251969815` before work.
The request builder reduced the shared search limit to the root declaration. The comparator
selected a count-frontier winner rather than the actual one-GW action. Both diagnoses were
confirmed in the parent implementation.

The optional `TransferActionScope` is included in search/request semantic hashes when present.
Absent fields are excluded from serialization to preserve prior one-GW and generic hashes.
The root keeps its effective declaration; continuation uses the existing search/rules cap and,
for automatic private scope, the current state's FT inventory. Explicit rules-bounded callers
retain hits. No incoming shortlist is widened. Enumerator memo tables belong to one immutable
request, and both node identity and FT inventory are already part of their state keys. The
same resolved cap is checked independently during plan replay.

The R2 root summary already retains the exact best continuation for each supported objective
and each root action. R4 retrieves the actual action's expected-optimal policy from this same
complete summary, avoiding another horizon solve. It validates the plan and seals it in the
result. Missing actions and incomplete enumeration cannot produce a successful counterfactual.
The rolling report compares that policy with the selected horizon winner using the existing
UtilityBreakdown signs. Same-count substitute logic is removed.

The synthetic incremental benchmark records 15 players, 3 retained incoming players, 3 GWs
and root FT=1. It compares the old cap, corrected accelerated enumeration and corrected generic
oracle with exact candidate equality. Timings use a synthetic tactical evaluator, not a live
football or Stage-10 runtime claim. Per-node profiles expose action counts by FT inventory,
memo hits, unique states and tactical squads. Actual live inputs are never persisted.

Measured incremental Stage-11 times were 0.382083 s (old cap), 0.592456 s (corrected fast),
and 1.721477 s (corrected generic): 1.55x the old bounded solve, while retaining a 2.91x
advantage over the corrected generic oracle. All have 14 root actions and 227 unique tactical
node/squad evaluations. The corrected fast run solves 84 node states and records 123 memo
hits; the generic run solves 207 and records none. At GW2, the held-FT=2 state gains 55 legal
two-transfer actions; FT=1 states still have no two-transfer actions. These are synthetic
measurements, not predictions of live runtime or recommendation quality.

The same-count hostile example selects different one-transfer root actions: the actual
one-GW action's three-GW counterfactual utility is 4, while the horizon winner is 23. The
decomposition is -1 current +20 later -0 hits +0 terminal = +19. The different-count example
prefers hold despite losing 5 immediate points because saved FT inventory enables the paired
future move. Tied zero-value policies deterministically hold; recourse is available, not forced.
