# R6 implementation review

This is implementation self-review, not an independent external acceptance certificate.
The exact-SHA CI result is a separate mandatory publication gate. No PR/merge/tag/activation.

## Authority and scope

- Parent `9c02ed86bf181c0a7e75c5983f08d23fe8824dc9`, exact-SHA CI `34483828704`: 12 successful jobs.
- Scope manifest A10/A11/B2: SHA256 `b780a757b922ab8fc70388de2651860f88908a96c5d91cc87bbabbdf555700ac`.
- DMFP-12 sections 25.2-25.4, 26 and 38: SHA256
  `cba15ba9c72ff68c0ea8dca6ac5cf9075bbb34eefca06e86060cf33f824a84f6`.
- DMFP-20 ADR-PROD-002, ADR-OPT-001..005, ADR-UNC-005/007: SHA256
  `7ed484961cf81af1716db6daa51e6fa05ce2584c33bb04c1d59698e3bf934d72`.
- DMFP-12 section 25.4 requires an upside escape. R6 permits, but does not require, removing
  the V2 upside bucket. V3 retains a clearly heuristic remaining-horizon upside escape;
  Stage-11 utility remains expected points. No authority text or decision was rewritten.

Production edits are the new private screen, private request/report/comparator/version wiring,
and the narrowly opted-in Stage-11 fast-path eligibility extension. Model inputs, official FPL
parsing, prices, ownership/FT transition rules, terminal semantics and dependency pins are unchanged.
One-GW ranking, dominance and screening bodies, plus the historical V2 function, compare
byte-identical to parent after newline normalization.

## Empirical design and correctness

V2 synthetic union 115 is reproduced without changing its bound: 9 ordinary metric candidates
plus complete cheapest-price tie groups become 115. Largest boundary tie is 28. Separate
low-overlap buckets produce union 36 without ties. The diagnostics include raw counts,
pairwise overlap, unique membership, cumulative categories and projected legal FT2 actions.

The first node-specific six-bucket prototype still hit the unchanged policy-count guard:
20/20/20 and 26/20/20 node scopes were not labelled complete. Final V3 instead uses nominal
top-two remaining expected, one price-route and one upside escape per position; target-GW
expected/price/remaining-GW vectors are declared secondary criteria. Independent target-GW
and ratio buckets were removed. The 18-player STANDARD bound follows four nominal slots per
position plus at most two actual comparator incoming players. It is not an arbitrary increase
to the observed live union. Exact residual ties are never identity-truncated.

An unchanged full-universe oracle exposed a prototype failure: both leading incoming players
could already be owned in the last GW, excluding a useful third move. V3 now fills overlapping
position buckets to three nominal candidates using the next remaining-expected ranks. This
heuristic depth escape passes the original hostile cases without changing oracle assertions.
Budget, club-release, positional redistribution, FT carry and actual one-GW pinned-action
counterfactual are included in five final reduced-universe oracle cases.

Each node admits candidates using only its remaining current-cutoff horizon; root admits
later-value targets. Allowed sets are in node information keys and sealed tree/request hashes;
the screen also binds projections, catalog/prices, protected incoming, memberships and budgets.
R2 reuse is safe because its memo key is `(node_id, economic_state_fingerprint)` within one
immutable request. Differing node sets are allowed only with the explicit sealed-node-scope
assumption. All other eligibility guards remain; old undeclared differing scopes still fail.
Fast/generic complete candidates match exactly, not merely objective values.

The actual unchanged one-GW action is solved first and protected at the root. Its root cache is
reused with identical root projection/catalog/tactical policy and a future-capable adapter.
State-dependent canonical simultaneous-transfer checks preserve FT2/bank/club routes before
each tactical batch. No unsound individual affordability exclusion is introduced.

## Final synthetic measurements

| Shape | Full | V2 union | V3 nodes | Exact fast seconds | Unique tactical node/squads |
|---|---:|---:|---|---:|---:|
| Large price tie | 115 | 115 (blocked) | 12/12/12 | 10.6901 | 2,767 |
| Low overlap | 80 | 36 (blocked) | 12/12/12 | 79.5468 | 76,727 |
| High overlap | 600 | 9 | 12/12/12 | 44.3438 | 8,997 |
| Near limit | 80 | 24 | 18/16/16 | 102.6184 | 28,484 |
| Reduced oracle benchmark | 5 | not applied | 3/3/3 | 0.6161 | 118 |

All five final cases complete. Reduced generic time is 1.8969s with byte-equal candidates and
the same 118 unique tactical keys. Screening takes approximately 0.0003-0.0112s. Timings are
single synthetic-surrogate measurements with possible concurrent acceptance CPU load, not
live Stage-10 timing claims. Full per-node legal FT/count actions, states, memo hits/misses and
tactical counts are in `benchmark.json`, alongside rejected-prototype evidence and source hashes.

## Limits and findings

Local acceptance includes the 306-test broad checkpoint, 216-test Stage-11 unit/property
matrix, 99-test fresh final suite and two comparator-failure tests. Changed-line/originating-arc
coverage is 100%, including originating statements for multiline condition/version changes.
Ruff, strict mypy, frozen sync, build, clean external installed-wheel checks, authority,
repository/manifests and secret scan passed. Exact-SHA CI is still a separate publication gate.
The full actual synthetic three-GW recommendation stack also ran from the installed wheel
in a clean external offline environment, with automatic V3 scope and the exact pinned comparator.
The first publication's CI exposed a test-only import-path defect during shard-plan collection.
Moving shared diagnostics from the CLI script into test support fixes the exact CI entry point
(4,389 eligible tests); all 20 R6 capacity/oracle tests pass afterward. Production and diagnostic
function bodies remain byte-identical. No CI selector, import mode or coverage threshold changed.

- This remains heuristic candidate admission, exact only inside its declared action space.
  The targeted full-universe matches are not a global optimality proof.
- No horizon dominance or model-equivalence removal is certified. Even equal means and
  prices do not erase scenario/appearance/club/co-ownership/cohort identity semantics.
- Final ties exceeding 18 still fail with safe pressure diagnostics. The unchanged legacy
  one-GW screen can independently fail its old guard; R6 does not change one-GW semantics.
- 17,000 action combinations per state and inherited 25,000-state/250,000-policy guards bound
  work, not wall time. Other valid inputs may still hit these guards; no scope changes after
  sealing and no resource-limited result is called optimal.
- No private runtime input or live raw provider body was used for the committed evidence.
  Live retry and survival of R4 HOLD cannot be inferred from synthetic tests.
- No new in-scope unresolved P0/P1/material P2 found in self-review. Independent external
  review and human acceptance remain separate and are not claimed here.
- The canonical review builder returns `REVIEW_TICKET_UNSUPPORTED` for R6. The handoff
  bundle is supplementary, capped at 20 flat files, and explicitly not a canonical ticket
  acceptance certificate. Governance tooling has not been changed to bypass that boundary.
