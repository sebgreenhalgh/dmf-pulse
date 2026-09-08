# Exactness and scope review

## Authority and boundary

Immutable parent: `43229ea760bc2b3587a4ed05e22bef3c9e505497`, accepted parent CI
`33741523810`. Scope resolution uses `specs/manifests/authority_manifest.json`,
`A10-one-GW-optimiser`, `A11-decision-bundle`, and `B2-multi-GW`.
DMFP-20 ADR-OPT-001/002/003/004/005 (lines 1610-1749), DMFP-12 sections 0.5,
4.3-4.6, 5-8, and the accepted 001L/M/N/R1 implementation contracts govern this change.
ADR-OPT-003 explicitly permits an equivalent compact state once validated and requires
repurchase to reset the purchase cohort. ADR-OPT-006 is PROVISIONAL, not a new dependency
authorization. The existing TEST/REPLAY/private bounded solver is accelerated; the production
backend remains blocked. This is not a replacement for the future production stochastic master.

## Verified parent facts

The private request builder reuses the same current-cutoff incoming shortlist and current prices
at three consecutive, probability-one nodes. It declares no new information revelation,
no chips, expected three-GW utility, and zero terminal value. The generic enumerator recursively
generates legal actions at each reached state and uses `(node_id, state_fingerprint(state))`.
That fingerprint includes every complete ownership spell. The private tactical memo uses
`(node_id, active squad IDs)`; the parent only precomputes the root, so future misses use the
individual exact Stage-10 routine.

The benchmark confirms redundant *economically equivalent* states. Its closed-history-only
duplicate count is zero: active spells' provenance IDs/start metadata also differ between
transfer histories. Therefore the measured problem must not be described as exclusively closed
history duplication. Both kinds of irrelevant provenance are omitted from the internal key,
while retained in every emitted ManagerState.

## Sufficient-state argument

Within one immutable request and decision node define K(S) as:

- current Gameweek and observed node;
- bank in integer tenths and free-transfer inventory;
- ruleset ID, version and hash;
- each active player's ID, club, position, purchase price and current price.

The catalog, rules, node prices/purchasability, retained incoming IDs, event and search policy
are request/node inputs, fixed for both states being compared. A tactical evaluator must
explicitly promise that its value depends only on the fixed node and active squad IDs.
Unpromised evaluators use the unchanged generic path.

The proof is scoped to reachable continuation states after the root, not arbitrary replay
histories. Dispatch excludes any initial spell whose start or closure lies after the root GW.
All memoised continuations are at later deadlines, so prior starts/closures cannot collide with
a new purchase's Gameweek or change ownership-overlap validation. The root itself is not
economically memoised. The generic model's more permissive future-dated replay histories
therefore remain on the generic path.

For such valid continuation states S and T with K(S)=K(T):

1. Owned IDs, purchasable incoming IDs and outgoing/incoming position multisets are identical.
   Thus the same transfer combinations are considered under the same original combination cap.
2. Each selling value is the same configured integer function of the active purchase and current
   prices. Buying prices are the same node prices. Bank after each action is therefore equal.
   Active club counts and exact position quotas are equal, so feasible action sets are equal.
3. The compiled FT event rule receives identical event, FT inventory and transfer count. Free
   use, paid transfers, hit points and next FT inventory are identical. No saved-FT point value
   is introduced.
4. Retained players keep the same purchase/current prices. A bought player starts a new cohort
   at the same node buying price. Sold cohorts close. The canonical function still creates and
   retains their distinct provenance IDs; those IDs do not change any future economic input.
   Hence applying the same action yields equal next K. Observing the next fixed node preserves
   equality of K.
5. The same resulting squad has the same canonical exact tactical evaluation, including its
   expected/p10/p90 values, tactic, diagnostics and tactical plan hash. Terminal value is zero.

Induct on the remaining node suffix: each feasible action has equal immediate utility and an
equal set of feasible continuation utility triples. The existing candidate construction,
Decimal arithmetic, Pareto routine, canonical tie key, root sufficient-family retention and
expected/conservative/upside selectors are not replaced. They consequently choose the same
full policy for every root action, each exact-count horizon bucket, baseline and alternative.
No cross-bank, cross-FT, cross-price, cross-club/position or cross-rule merging occurs.

## Replay and artifact identity

An economic memo hit cannot publish the cached caller's history. It replays the cached suffix's
actions using the unchanged `apply_transfer_action` and `observe_node` on the *actual caller's*
full ManagerState. Each step checks equal economic next state and equal exact tactical result.
The rebuilt NodeDecisions retain the caller's complete state chain, closed spells, fresh
repurchase IDs, transfer prices, bank/FT and state hashes. Full candidate dataclass equality
against the generic oracle includes these histories and hashes, not just utilities.

Stage-11 physical diagnostics deliberately count less work. A plan/result digest that encloses
those diagnostics therefore changes. Publication tests independently verify the original sealed
result, and normalize only five physical counters (`state_expansions`, `action_candidates`,
`policy_candidates`, `pareto_candidates`, `memo_entries`) and their enclosing Stage-11
plan/frontier/result digests. All other fields, including every tactical and ownership-state
hash, remain in the exact comparison. No decision/artifact contract is weakened.

## Other lossless transformations

The fast path retains canonical AppliedTransfer values already computed to establish legality,
avoiding a second application for the same `(full state hash, action ID)`.
Its optional legality precheck first validates the manager state and computes exact configured
selling prices. It rejects only negative resulting bank or excess resulting club counts.
It subtracts all outgoing clubs before adding incoming clubs, preserving two-move club-slot
release. Every combination still increments the original cap counter *before* this check.
Every surviving action still passes through canonical full transition validation. The generic
path does not use this precheck.

At each fast-path state, all canonically reachable resulting squads are deduplicated and sent
to `precompute_node`. Only missing `(node, squad IDs)` keys invoke `evaluate_many`; later
evaluation and replay reuse the same immutable result. No unreachable squad is evaluated.
The exact 001L node kernel is reused across these lazy batches. A deep snapshot comparison
rebuilds it if node prices, rules or scenarios change, including nested dictionary mutations.
There is no scenario reduction or player-points-sum approximation in runtime code.

## Dispatch, progress and limitations

Dispatch is explicit and requires exactly three distinct consecutive probability-one nodes in
one linear chain, the private assumptions, no information/availability/fixture revelation,
unchanged prices/shortlist, NORMAL transitions, and disabled all-zero terminal coefficients.
The specialised enumerator itself rejects invalid preconditions; public dispatch falls back
to the retained generic enumerator. Existing resource limits remain fail-closed and an
incomplete search cannot claim exact optimality.

Run-local counters report entered/solved/full/economic states, combinations and transfer-count
distribution, transitions, resulting squads, Pareto and memo work by depth. Tactical cache
counters separately report hits/misses, batches/individual calls, unique evaluations and time
by node. Enumeration time includes its transition-validation time; these timings overlap and
must not be added. Frontier profiles exclude separate baseline and publication validation work;
the private tactical cache totals include all work through those stages. Progress is throttled
at 30-second intervals and contains Gameweeks and aggregate counts, not player identities,
percentages, ETA or unproved incumbents.

The generic oracle remains tractable only on bounded synthetic universes. The live-shaped
benchmark is explicitly synthetic and budget-constrained, not a promised real-entry latency.
The structural surrogate is confined to benchmark/tests. Existing exact Stage-10 differential
tests and a separate real-Stage-10 benchmark cover the tactical path. No private identifier,
credential, provider response, or private state is included in committed evidence.

This is an implementation self-review. Human acceptance and any independently commissioned
review remain separate; no PR, merge, tag or production activation is performed.
