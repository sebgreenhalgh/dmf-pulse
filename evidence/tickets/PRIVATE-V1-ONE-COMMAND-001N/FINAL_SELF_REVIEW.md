# PRIVATE-V1-ONE-COMMAND-001N final self-review

## Semantics and compatibility

- Work is rooted at immutable parent `ad155c077253a0525f0c7406e955240146823f80` on the required
  isolated branch; the unrelated dirty root worktree was not modified.
- Explicit three-GW mode contains exactly the current, next, and following Gameweeks. The default
  remains one GW, and the accepted one-GW input/result contracts and frozen semantic hashes remain
  unchanged.
- Every horizon projection is constructed from one current cutoff through the accepted Stage-7,
  score-prior/market, Stage-8, and Stage-9 paths. Official future fixture identity, teams, kickoff,
  current-cutoff lineage, projection artifacts, and fallback coverage are hash-bound.
- The production solver is the existing Stage-11 bounded exact engine. The independent oracle is
  test-only and does not share the production decision selector.

## Transfer and objective correctness

- The root horizon frontier selects the exact best complete expected-utility policy for each root
  transfer count, using the existing canonical tie key.
- FT before/action/next-deadline state, hit points, integer bank, selling-price ownership spells,
  and squad paths are replayed by the accepted state transition engine.
- The rolling transfer ceiling is copied from the governed current candidate policy rather than
  hard-coded in 001N; request construction further intersects it with compiled rules, Stage-11
  search policy, available incoming candidates, and squad capacity.
- The terminal policy is the accepted disabled zero terminal after GW+2. There is no arbitrary
  free-transfer bonus, bank bonus, or liquidation value.
- One-GW-versus-three-GW explanations reconcile a structured objective decomposition and make no
  causal claim beyond the computed counterfactual policies.

## Safety and limitations

- Only the current root action is `DO_NOW`; later actions are always
  `PROVISIONAL_REOPTIMISE_AT_DEADLINE`.
- Future current-market absence is explicit score-prior-only coverage, never probability zero,
  stale odds, fabricated odds, or silent fixture omission. Insufficient accepted input blocks.
- Future prices are held constant, the scenario chain reveals no new information, chips/rank are
  off, and cross-fixture injury/dismissal/fatigue/readiness transitions are not newly propagated.
- Exactness is only within `PRIVATE_CURRENT_TRANSFER_CANDIDATE_PRUNING_V1`; no global FPL optimum
  is claimed.
- Provider access remains read-only, operator-initiated, transient, and no-retention. No live run
  occurs before exact-SHA CI.

No unresolved P0, P1, or material P2 finding is known. Exact final-SHA CI and the optional
credential-presence/live decision are completion-handoff facts and are not self-referentially
embedded in the implementation commit.
