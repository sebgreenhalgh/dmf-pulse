# R6 bounded horizon search contract

Parent R5 SHA is `9c02ed86bf181c0a7e75c5983f08d23fe8824dc9`. Its V2 screen unions all
complete buckets then fails above 24. The R6 synthetic analogue reproduces union 115:
ordinary metrics retain 9, then cheapest-price ties expand to 115 (largest tie 28).
Another 80-incoming low-overlap case produces V2 union 36 without ties. These are
synthetic reproductions, not retained live observations or private input reconstructions.

## V3 policy

`PRIVATE_HORIZON_TRANSFER_CANDIDATE_PRUNING_V3` constructs one scope for each node from
that node's remaining current-cutoff projections. Root sees all three GWs; second sees
two; last sees one. Current eligibility, catalog, prices and upstream guards do not change.
Per position, retain these explicitly heuristic buckets with complete final rank ties:

- top two by `(remaining expected sum, target-GW expected, negative price, remaining GW vector)`;
- cheapest price route by `(negative price, remaining expected sum, target-GW expected, vector)`;
- one upside escape by `(remaining sum of mean plus standard deviation, remaining expected sum,
  target-GW expected, negative price, vector)`.

If these overlap to fewer than three candidates, admit the next remaining-expected candidates
not already retained until three nominal candidates exist; preserve the complete cutoff tie.
The depth escape responds to an observed oracle failure where both leaders were already
owned at the last GW. It is not a substitution proof or a claim of complete route coverage.
Position universes of at most four retain every member. The actual accepted one-GW action's
incoming players (at most two), not its entire shortlist, are protected at the root only.

Target-GW expected and price become lexicographic criteria, not additional full unions.
There is no independent expected/price-ratio bucket in V3: cheap routes remain deliberately
represented and remaining expected points is the primary objective-aligned rank. The separate
upside escape remains explicitly heuristic under DMFP-12 section 25.4; neither variance nor
price/value is added to the Stage-11 objective. No arbitrary GW weights or identity ranking.
Decimal conversions and 28-digit half-even context follow V2 numerical conventions.

## Budget and exactness

V3 STANDARD permits at most 18 incoming players per node: four nominal slots per position
plus at most two comparator incoming players. Complete residual ties may use spare capacity;
larger groups fail with counts, positions, categories, protected counts, tie pressure and policy.
No identity/hash/name/source-order cutoff, silent scope reduction or equivalence compression.
Certified horizon dominance and exact model-equivalence removals are both zero: pairwise
equality/superiority does not prove irrelevance of co-ownership, club or cohort routes.

The action-combination budget is 17,000 per state (the unfiltered 15-owned/18-incoming,
at-most-two-transfer bound is 16,336). Inherited state/policy guards remain 25,000/250,000;
no thresholds are relaxed. The cap is not a universal completion/runtime guarantee.
Prototype six-bucket scope (26-player cap) hit the inherited policy guard with 20/20/20
and 26/20/20 retained; that measured pressure motivated the smaller admission policy.
All final benchmark completions and resource failures must be disclosed, never called optimal.
State-dependent canonical positional/club/bank/selling-price/FT legality runs before each
state's tactical batch. No single-transfer affordability pruning removes funded pair routes.

Each node's allowed set binds its information key and sealed tree/request. Projection/catalog/
price/protected/bucket/output/policy/budget inputs also bind a screen hash in request assumptions.
`SEALED_NODE_SPECIFIC_CANDIDATE_SCOPE_V1` explicitly permits differing node sets in the R2 fast
path. Its memo key already includes node ID: no economic-state memo entry crosses node scope.
Other fast-path preconditions remain unchanged. Generic/accelerated candidates must match
exactly within the same request; reduced full-universe oracles compare complete non-identity
economic/tactical decisions, excluding only scope-derived state/information/spell identities.

One-GW V1 ranking/dominance/screen functions are unchanged. Solve that exact action first,
protect it, and retain R4's pinned-action optimal continuation, FT-only future recourse and
WHY CHANGED decomposition. Reuse its same-projection squad-only tactical cache at the root.
Reports remain `EXACT_ONLY_WITHIN_DECLARED_CANDIDATE_ACTION_SPACE`, never globally exhaustive.

## Acceptance and publication

Run new capacity/tie/shuffle/renaming/node/hash/oracle tests; R5 screen/oracle regressions;
R2/R4 fast/generic/FT/comparator matrices; one-GW/frontier/private rolling and R3 ingestion.
Measure changed-code branch coverage. Run repository-wide Ruff format/check, strict mypy,
frozen sync, build, clean external installed-wheel validation, authority/repository validation,
secret scan, manifest tests and git diff check. Regenerate active PRC-013 and R6 manifests.
Benchmark large-tie, low/high-overlap, near-limit and reduced generic cases with safe counts.
Push one exact SHA and require all exact-SHA CI jobs. Live retry only after green CI with
already-present runtime inputs; do not request credentials. No PR/merge/tag/activation.
