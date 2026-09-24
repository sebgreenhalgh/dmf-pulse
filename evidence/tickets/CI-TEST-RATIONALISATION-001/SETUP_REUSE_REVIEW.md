# Expensive setup reuse review

The dominant expensive modules were inspected before changing fixture scope.

- The five canonical team-strength cases already share one module-scoped frozen
  model preparation. Their remaining cost is five distinct real comparisons.
- Shadow-comparison and D1 diagnostic modules already share their costly real
  preparation; downstream tamper/fail-closed cases are inexpensive.
- Optimiser service, terminal, horizon, and R2C cases use different states/oracles;
  sharing solved results would invalidate equivalence or legality protection.
- Prepared-runner D3 cases require fresh transports, request counters, monkeypatches,
  write guards, and service state.

A bounded D3 experiment shared only immutable provider-shaped payload/config
construction and added an isolation check. The complete module changed from
412.76s (5 tests) to 411.57s (6 tests). The 1.19s difference is within run noise
and the dominant four calls remained 96.68-100.54s each. The experiment was
reverted rather than retaining fixture complexity without material benefit.

Final expensive setups newly shared: 0. Existing safe module-scoped reuse is
retained. Stateful service/model/solver results are not cached, preserving order,
RNG, request-ledger, and mutation isolation.
