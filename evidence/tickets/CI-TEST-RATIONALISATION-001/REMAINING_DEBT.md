# Remaining test-architecture debt

- The deterministic shard planner still embeds static `FILE_WEIGHT_OVERRIDES`.
  Two weights are demonstrably stale, but replacing the versioned map with robust
  timing history is deferred because Phase-1 CI is healthy and weights cannot alter
  test selection. A Phase-3 change should introduce a committed timing manifest,
  conservative unseen-module fallback, and staleness metadata.
- Generic combined coverage is still written to the historical GCS-008 evidence
  path and checked by GCS-named scripts. Renaming that infrastructure would touch
  workflow, validators, ticket evidence, wheel checks, and immutable historical
  references. It is deliberately deferred rather than expanding this correctness
  and cadence change.
- The 759-node deep view is a repeat of tests that remain mandatory in full CI.
  No nightly-only workflow was added because doing so would add CI policy without
  reducing the current healthy blocking gate.
- Per-module unique branch coverage is recorded as `NOT_ISOLATED` in the inventory.
  This phase requires successor/counterfactual evidence for removals and does not
  infer uniqueness from global coverage percentage.
