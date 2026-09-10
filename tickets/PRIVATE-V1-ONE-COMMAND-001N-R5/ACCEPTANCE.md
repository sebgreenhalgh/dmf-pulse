# R5 bounded screen contract

`PRIVATE_HORIZON_TRANSFER_CANDIDATE_PRUNING_V2` applies only to automatic three-GW requests.
The upstream selectable, eligible non-squad universe is unchanged. One horizon union is reused
at root and future nodes. The accepted one-GW screen and recommendation path stay unchanged.

For each position, union top-two expected points, top-one mean-plus-standard-deviation upside,
and top-one expected-points/price in every active GW; add top-two additive horizon expected
points and top-one aggregate expected-points/price. No arbitrary GW weights are introduced.
When prices differ, retain all cheapest-price ties as price-route escape candidates. Retain
all members of position universes of size at most four. Include the complete accepted root
one-GW shortlist to guarantee availability of its actual-action horizon counterfactual.
Metric boundary ties are complete. Categories overlap and their counts are not additive.

V2 STANDARD retains the explicit 24-player safety bound, not an arbitrary larger cutoff.
The distinct-bucket and oversized-tie tests demonstrate unions that exceed it; such requests
fail with a scope error. V2 is not guaranteed to accept every possible metric union. No player
ID, hash or source-order fallback truncates the union. The inherited 25,000-state and other
exact search resource guards remain unchanged. A retained-count bound is not a promise that
every price/club configuration will fit the exact runtime budget. A larger budget requires a
separate measured revision; R5 does not invent feasibility evidence for it.

No horizon dominance removals are certified. Same position/club, no higher static price,
identical appearances and pointwise superiority across every GW are still insufficient to
prove safe substitution when both players can be owned or when a transfer route depends on
their distinct identities/cohorts. Retaining false negatives is intentional. Heuristic
exclusions remain labelled heuristic, never certified dominance.

Projection hashes, eligible catalog, static prices, horizon, root transfer limit, complete
bucket memberships, output and policy/bound bind the screen hash. This hash is part of the
Stage-11 request assumptions; node allowed sets also bind information/state identities. No
node-specific or future-information acquisition semantics are introduced.

Retain R2 accelerated/generic equality, R4 FT-only continuation and actual-action comparator,
one-GW compatibility, and exact-within-declared-action-space labels. Reduced complete-universe
oracles compare all economic/tactical policy fields; request-derived information/state/spell
identifiers necessarily differ between different candidate universes. Within one request,
fast/generic candidates must remain byte-identical.

Acceptance includes new and inherited tests, changed branch coverage, strict typing, Ruff,
frozen sync, build/installed wheel, authority/repository/manifests, secret scan and diff check.
Regenerate active PRC-013 and ticket manifests before publication. Require full exact-SHA CI.
Live retry is optional only after CI and with already-present runtime inputs. No PR/merge/tag.
