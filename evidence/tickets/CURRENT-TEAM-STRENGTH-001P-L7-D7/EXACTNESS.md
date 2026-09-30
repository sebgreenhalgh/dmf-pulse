# Exactness and physical-work remediation

D7 replaces per-node materialisation followed by a second Pareto pass with an exact
incremental Pareto accumulator. It evaluates and counts every logical candidate,
retains the lexicographically deterministic representative for equal sufficient
statistics, removes no candidate except by strict dominance or exact tie equivalence,
and preserves the exact best candidate for `EXPECTED`, `CONSERVATIVE`, and
`HIGH_UPSIDE` for every root action.

Profile counters distinguish strict Pareto-dominance events from equal-score
deterministic tie-equivalence events. Equal score vectors retain the lowest canonical
tie key; they are never described as strict dominance.

The reducer removes only strictly dominated candidates or equal-score duplicates for
which the canonical tie-key representative is retained. The root accumulator retains
the union of:

- the exact global Pareto frontier; and
- every root action's exact winner for each supported objective.

This is the same sufficient result family used by the materialised implementation for
the recommendation, alternatives, no-transfer baseline, root counterfactual, transfer
frontier, move attribution, and future policy. D6 deterministic layered-baseline reuse
and `deterministic_linear_fast_path_selected()` remain the single path authority.

Forward discovery now retains the complete deterministic legal-action layers but
consumes each heavyweight `AppliedTransfer` immediately after deriving its squad and
next state. Backward scoring replays the unchanged canonical transition from the
retained action. This losslessly trades additional transition work for bounded memory;
it removes no action, state, policy or frontier. A direct generic-versus-layered oracle
proves identical candidates and an empty retained-transition map after completion.

Governed-cap and 10-million reference runs produced identical decision semantics:

- baseline-like: `3fb1df08c27e063869f8922f71f2634b11c907fa3f8385325835d3f2769403bb`;
- shifted-shadow-like: `f5d4df2085e46bd4d7084e278c157f1ac6ca1a0f3d145226da43d9af968dcda8`.

Each comparison covers the recommended plan, no-transfer baseline, root
counterfactual, complete transfer-count frontier, future policy and objective
utilities. Full result hashes intentionally differ across authenticated policies and
physical-work diagnostics, so equality is asserted on underlying decision semantics.

Peak temporary policy populations were 1,032 in the baseline-like case and 1,271 in
the shifted case. A reviewer-observed Windows `PeakWorkingSet64` for the completed
baseline-high process was 1,827,266,560 bytes. This is platform-local context, not a
portable governed memory metric. Before transition replay, safely terminated
exploratory runs exceeded 8 GB at incomplete smaller workloads; they are not acceptance
evidence.
